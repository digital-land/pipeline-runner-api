import csv
import os
from pathlib import Path
import logging

from digital_land.phase.phase import Phase
from digital_land.phase.convert import ConvertPhase
from digital_land.phase.normalise import NormalisePhase
from digital_land.phase.parse import ParsePhase
from digital_land.phase.concat import ConcatFieldPhase
from digital_land.phase.map import MapPhase
from digital_land.phase.filter import FilterPhase
from digital_land.phase.patch import PatchPhase
from digital_land.phase.harmonise import HarmonisePhase
from digital_land.phase.default import DefaultPhase
from digital_land.phase.migrate import MigratePhase
from digital_land.phase.organisation import OrganisationPhase
from digital_land.phase.prune import FieldPrunePhase
from digital_land.phase.reference import EntityReferencePhase
from digital_land.phase.prefix import EntityPrefixPhase
from digital_land.phase.save import SavePhase
from digital_land.pipeline import run_pipeline, Pipeline
from digital_land.specification import Specification
from digital_land.organisation import Organisation

from digital_land.log import DatasetResourceLog, ColumnFieldLog, IssueLog


from digital_land.commands import resource_from_path

from digital_land.phase.lookup import key

lookup_file_path = "./pipeline/lookup.csv"


# print all lookups that aren't found will need to read through all files
class UnassignedEntries(Phase):
    def __init__(self, lookups={}):
        self.lookups = lookups
        self.entity_field = "entity"

    def lookup(self, **kwargs):
        return self.lookups.get(key(**kwargs), "")

    def process(self, stream):
        for block in stream:
            row = block["row"]
            entry_number = block["entry-number"]
            prefix = row.get("prefix", "")
            reference = row.get("reference", "")
            organisation = row.get("organisation", "")
            if prefix:
                if not row.get(self.entity_field, ""):
                    entity = (
                        # by the resource and row number
                        (
                            self.entity_field == "entity"
                            and self.lookup(prefix=prefix, entry_number=entry_number)
                        )
                        # TBD: fixup prefixes so this isn't needed ..
                        # or by the organisation and the reference
                        or self.lookup(
                            prefix=prefix,
                            organisation=organisation,
                            reference=reference,
                        )
                    )

            if not entity:
                block["row"] = {
                    "prefix": prefix,
                    "organisation": organisation,
                    "reference": reference,
                }
                yield block


def save_resource_unidentified_lookups(
    input_path,
    dataset,
    organisations,
    pipeline_dir="./pipeline",
    specification_dir="./specification",
):
    #  define pipeline and specification
    pipeline = Pipeline(pipeline_dir, dataset)
    specification = Specification(specification_dir)

    # convert phase inputs
    resource = resource_from_path(input_path)
    dataset_resource_log = DatasetResourceLog(dataset=dataset, resource=resource)
    custom_temp_dir = "./var"

    # normalise phase inputs
    skip_patterns = pipeline.skip_patterns(resource)
    null_path = None

    # concatfieldphase
    concats = pipeline.concatenations(resource)
    column_field_log = ColumnFieldLog(dataset=dataset, resource=resource)

    # map phase
    intermediate_fieldnames = specification.intermediate_fieldnames(pipeline)
    columns = pipeline.columns(resource)

    # patch phase
    patches = pipeline.patches(resource=resource)

    # harmonize phase
    issue_log = IssueLog(dataset=dataset, resource=resource)

    # default phase
    default_fields = pipeline.default_fields(resource=resource)
    default_values = pipeline.default_values(endpoints=[])

    if len(organisations) == 1:
        default_values["organisation"] = organisations[0]

    # migrate phase
    schema = specification.pipeline[pipeline.name]["schema"]

    # organisation phase
    organisation = Organisation(
        os.path.join("var", "cache", "organisation.csv"), Path(pipeline.path)
    )

    # print lookups phase
    flookups = pipeline.lookups()

    run_pipeline(
        ConvertPhase(
            path=input_path,
            dataset_resource_log=dataset_resource_log,
            custom_temp_dir=custom_temp_dir,
        ),
        NormalisePhase(skip_patterns=skip_patterns, null_path=null_path),
        ParsePhase(),
        ConcatFieldPhase(concats=concats, log=column_field_log),
        MapPhase(
            fieldnames=intermediate_fieldnames,
            columns=columns,
            log=column_field_log,
        ),
        FilterPhase(filters=pipeline.filters(resource)),
        PatchPhase(
            issues=issue_log,
            patches=patches,
        ),
        HarmonisePhase(
            specification=specification,
            issues=issue_log,
        ),
        DefaultPhase(
            default_fields=default_fields,
            default_values=default_values,
            issues=issue_log,
        ),
        # TBD: move migrating columns to fields to be immediately after map
        # this will simplify harmonisation and remove intermediate_fieldnames
        # but effects brownfield-land and other pipelines which operate on columns
        MigratePhase(
            fields=specification.schema_field[schema],
            migrations=pipeline.migrations(),
        ),
        OrganisationPhase(
            organisation=organisation,
            issues=issue_log,
        ),
        FieldPrunePhase(fields=specification.current_fieldnames(schema)),
        EntityReferencePhase(
            dataset=dataset,
            specification=specification,
        ),
        EntityPrefixPhase(dataset=dataset),
        UnassignedEntries(lookups=flookups),
        SavePhase(
            path=Path("./var/cache/unassigned-entries.csv"),
            fieldnames=["prefix", "organisation", "reference"],
        ),
    )
    # issue_log.save(os.path.join("issue", dataset, resource + ".csv"))


def standardise_lookups(lookups_path):
    """
    standardise and sort the current lookup.csv file.
    Specifically to ensure the correct columns are all there
    and that it is ordered by entity number.
    """
    expected_fieldnames = ["prefix", "resource", "organisation", "reference", "entity"]
    lookups = []
    fieldnames = []
    with open(lookups_path) as f:
        dictreader = csv.DictReader(f)
        fieldnames = dictreader.fieldnames
        for row in dictreader:
            lookups.append(row)

    for fieldname in fieldnames:
        if fieldname not in expected_fieldnames:
            logging.warning(f"{fieldname}: unexpected fieldname in lookups.csv")

    # reorder lookups
    lookups = sorted(lookups, key=lambda d: d["entity"])
    with open(lookups_path, "w") as f:
        dictwriter = csv.DictWriter(f, fieldnames=fieldnames)
        dictwriter.writeheader()
        dictwriter.writerows(lookups)


def add_unnassigned_to_lookups(
    unassigned_entries,
    lookups_path,
):
    fieldnames = []
    dataset_max_entity_ref = {}
    # get fieldnames from lookup.csv
    # get maximum entity numbers by dataset
    with open(lookups_path) as f:
        dictreader = csv.DictReader(f)
        fieldnames = dictreader.fieldnames
        for row in dictreader:
            if dataset_max_entity_ref.get(row["prefix"], ""):
                if dataset_max_entity_ref[row["prefix"]] < int(row["entity"]):
                    dataset_max_entity_ref[row["prefix"]] = int(row["entity"])
            else:
                dataset_max_entity_ref[row["prefix"]] = int(row["entity"])

    # assign the entity
    # TO DO expand this so that if there are unnassigned entries with datasets
    #  not already in the list then it doesn't error
    for entry in unassigned_entries:
        print(entry)
        entry["entity"] = dataset_max_entity_ref[entry["prefix"]] + 1
        dataset_max_entity_ref[entry["prefix"]] = (
            dataset_max_entity_ref[entry["prefix"]] + 1
        )

    # save the assignmeents
    with open(lookups_path, "a") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writerows(unassigned_entries)

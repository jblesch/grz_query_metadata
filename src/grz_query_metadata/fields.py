"""What to survey: metadata paths of the fields the survey counts.

Both dictionaries map a short label to a path through the submission metadata
document, where a ``[]`` suffix descends into an array. The same paths are used
twice: by :mod:`grz_query_metadata.survey` to count values, and by
:mod:`grz_query_metadata.schema` to walk a JSON Schema to the same places.

ENUM_FIELDS
    Controlled vocabularies in the current schema. Values are safe to report
    verbatim; that is the whole point.
FREETEXT_FIELDS
    Uncontrolled today. Counted just like the enum fields, but their distinct
    values are written out verbatim as well, so that coverage against a proposed
    vocabulary can be measured. That verbatim part is what makes them worth
    REVIEWING BEFORE SHARING.
"""

from __future__ import annotations

import re

ENUM_FIELDS: dict[str, str] = {
    "submission.submissionType": "submission/submissionType",
    "submission.coverageType": "submission/coverageType",
    "submission.diseaseType": "submission/diseaseType",
    "submission.genomicStudyType": "submission/genomicStudyType",
    "submission.genomicStudySubtype": "submission/genomicStudySubtype",
    "donors.gender": "donors[]/gender",
    "donors.relation": "donors[]/relation",
    "researchConsents.noScopeJustification": "donors[]/researchConsents[]/noScopeJustification",
    "labData.sampleConservation": "donors[]/labData[]/sampleConservation",
    "labData.sequenceType": "donors[]/labData[]/sequenceType",
    "labData.sequenceSubtype": "donors[]/labData[]/sequenceSubtype",
    "labData.fragmentationMethod": "donors[]/labData[]/fragmentationMethod",
    "labData.libraryType": "donors[]/labData[]/libraryType",
    "labData.enrichmentKitManufacturer": "donors[]/labData[]/enrichmentKitManufacturer",
    "labData.sequencingLayout": "donors[]/labData[]/sequencingLayout",
    "tumorCellCount.method": "donors[]/labData[]/tumorCellCount[]/method",
    "sequenceData.referenceGenome": "donors[]/labData[]/sequenceData/referenceGenome",
    "files.fileType": "donors[]/labData[]/sequenceData/files[]/fileType",
    "files.readOrder": "donors[]/labData[]/sequenceData/files[]/readOrder",
    "files.checksumType": "donors[]/labData[]/sequenceData/files[]/checksumType",
}

FREETEXT_FIELDS: dict[str, str] = {
    "labData.tissueOntology.name": "donors[]/labData[]/tissueOntology/name",
    "labData.tissueOntology.version": "donors[]/labData[]/tissueOntology/version",
    "labData.tissueTypeId": "donors[]/labData[]/tissueTypeId",
    "labData.tissueTypeName": "donors[]/labData[]/tissueTypeName",
    "labData.libraryPrepKit": "donors[]/labData[]/libraryPrepKit",
    "labData.libraryPrepKitManufacturer": "donors[]/labData[]/libraryPrepKitManufacturer",
    "labData.sequencerModel": "donors[]/labData[]/sequencerModel",
    "labData.sequencerManufacturer": "donors[]/labData[]/sequencerManufacturer",
    "labData.kitName": "donors[]/labData[]/kitName",
    "labData.kitManufacturer": "donors[]/labData[]/kitManufacturer",
    "labData.enrichmentKitDescription": "donors[]/labData[]/enrichmentKitDescription",
    "labData.labDataName": "donors[]/labData[]/labDataName",
    "sequenceData.bioinformaticsPipelineName": "donors[]/labData[]/sequenceData/bioinformaticsPipelineName",
    "callerUsed.name": "donors[]/labData[]/sequenceData/callerUsed[]/name",
}

# \Z, not $: $ would also match just before a trailing newline, letting a
# copy-paste artefact like "BTO:0000089\n" pass as a well-formed id.
BTO_ID = re.compile(r"^BTO:[0-9]{7}\Z")


def split_segment(segment: str) -> tuple[str, bool]:
    """One path segment as (object key, descends-into-array?).

    The single definition of the ``[]`` suffix rule. Both consumers of the
    paths above — the survey's document walk and the schema walk — parse
    segments through this, so they cannot drift apart in how they read a path.
    """
    if segment.endswith("[]"):
        return segment[:-2], True
    return segment, False

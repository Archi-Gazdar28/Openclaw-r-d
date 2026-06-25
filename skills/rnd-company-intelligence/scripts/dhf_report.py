#!/usr/bin/env python3
"""
Regulatory knowledge system with a DHF rendering layer.

This module intentionally avoids using an LLM for engineering facts. It accepts
only product name and company name, resolves a device profile from deterministic
knowledge libraries plus public-source retrieval, runs contamination gates, and
renders a Design History File package.

Network lookups use free public endpoints where available:
- PubMed E-utilities
- Europe PMC
- ClinicalTrials.gov v2
- openFDA device 510(k), classification, and recall APIs

The renderer writes JSON and HTML by default. If reportlab is installed, it also
writes a PDF. If any mandatory identity, standards, predicate, risk, traceability,
or clinical relevance gate fails, generation stops.
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import html
import json
import subprocess
import re
import sys
import textwrap
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


CONFIDENCE_THRESHOLD = 0.95
CLINICAL_RELEVANCE_THRESHOLD = 0.72
DEFAULT_TIMEOUT_SECONDS = 18
USER_AGENT = "Nupat-DHF-Regulatory-Knowledge-System/1.0"


class DHFGenerationError(RuntimeError):
    """Raised when a quality gate blocks DHF generation."""


@dataclass(frozen=True)
class DeviceProfile:
    device_name: str
    manufacturer: str
    device_category: str
    device_family: str
    intended_use: str
    technology_type: str
    risk_class: str
    implantable: bool
    sterile: bool
    materials: List[str]
    markets: List[str]
    confidence: float
    identity_sources: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class UserNeed:
    id: str
    statement: str


@dataclass(frozen=True)
class DesignInput:
    id: str
    user_need_id: str
    parameter: str
    acceptance_basis: str
    regulatory_basis: List[str]


@dataclass(frozen=True)
class DesignOutput:
    id: str
    design_input_id: str
    artifact: str
    source: str


@dataclass(frozen=True)
class VerificationMethod:
    id: str
    design_input_id: str
    method: str
    acceptance_basis: str
    standard: str


@dataclass(frozen=True)
class ValidationMethod:
    id: str
    design_input_id: str
    method: str
    evidence_type: str


@dataclass(frozen=True)
class Hazard:
    id: str
    hazard: str
    foreseeable_sequence: str
    hazardous_situation: str
    harm: str
    risk_control: str
    residual_risk: str
    benefit_risk: str


@dataclass(frozen=True)
class EvidenceRecord:
    source: str
    title: str
    url: str
    identifier: str
    year: Optional[str]
    relevance_score: float
    decision: str
    rationale: str


@dataclass(frozen=True)
class PredicateRecord:
    source: str
    device_name: str
    applicant: str
    identifier: str
    product_code: str
    decision_date: str
    compatibility_score: float
    decision: str
    rationale: str


@dataclass(frozen=True)
class DeviceLibrary:
    family: str
    category: str
    technology_type: str
    intended_use: str
    default_risk_class: str
    implantable: bool
    sterile: bool
    allowed_materials: List[str]
    user_needs: List[UserNeed]
    design_inputs: List[DesignInput]
    verification_methods: List[VerificationMethod]
    validation_methods: List[ValidationMethod]
    hazards: List[Hazard]
    standards: List[str]
    regulations: List[str]
    guidance: List[str]
    product_codes: List[str]
    predicate_search_terms: List[str]
    clinical_search_terms: List[str]
    forbidden_terms: List[str]
    required_terms: List[str]


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def normalize(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", value.lower())).strip()


def tokenize(value: str) -> set[str]:
    return {tok for tok in normalize(value).split() if len(tok) > 2}


def safe_get_json(url: str, timeout: int = DEFAULT_TIMEOUT_SECONDS) -> Optional[Dict[str, Any]]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8", errors="replace"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError):
        pass
    try:
        completed = subprocess.run(
            ["curl", "-sS", "-m", str(timeout), url],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout + 2,
        )
        if completed.returncode == 0 and completed.stdout.strip():
            return json.loads(completed.stdout)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return None
    return None


def safe_get_text(url: str, timeout: int = DEFAULT_TIMEOUT_SECONDS) -> Optional[str]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/xml,text/plain,*/*"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError):
        return None


def score_relevance(text: str, library: DeviceLibrary, profile: DeviceProfile) -> Tuple[float, str]:
    haystack = normalize(text)
    haystack_terms = tokenize(haystack)
    required_terms = tokenize(" ".join(library.required_terms))
    clinical_terms = tokenize(" ".join(library.clinical_search_terms))
    product_terms = tokenize(profile.device_name)
    family_terms = tokenize(profile.device_family + " " + profile.technology_type)
    forbidden = []
    for term in library.forbidden_terms:
        normalized = normalize(term)
        term_tokens = tokenize(normalized)
        if len(term_tokens) == 1:
            if next(iter(term_tokens)) in haystack_terms:
                forbidden.append(term)
        elif normalized in haystack:
            forbidden.append(term)
    required_hits = sorted(required_terms & haystack_terms)
    clinical_hits = sorted(clinical_terms & haystack_terms)
    product_hits = sorted(product_terms & haystack_terms)
    family_hits = sorted(family_terms & haystack_terms)
    hits = sorted(set(required_hits + clinical_hits + product_hits + family_hits))
    family_bonus = 0.2 if normalize(profile.device_family) in haystack or normalize(profile.technology_type) in haystack else 0.0
    product_bonus = 0.15 if normalize(profile.device_name) in haystack else 0.0
    company_bonus = 0.08 if normalize(profile.manufacturer) in haystack else 0.0
    required_score = len(required_hits) / max(1, len(required_terms)) * 0.48
    clinical_score = min(0.18, len(clinical_hits) / max(1, len(clinical_terms)) * 0.18)
    family_score = min(0.12, len(family_hits) / max(1, len(family_terms)) * 0.12)
    product_score = min(0.08, len(product_hits) / max(1, len(product_terms)) * 0.08)
    all_required_bonus = 0.12 if required_terms and required_terms.issubset(haystack_terms) else 0.0
    penalty = min(0.5, len(forbidden) * 0.18)
    score = max(
        0.0,
        min(
            1.0,
            required_score
            + clinical_score
            + family_score
            + product_score
            + all_required_bonus
            + family_bonus
            + product_bonus
            + company_bonus
            - penalty,
        ),
    )
    rationale = f"matched_terms={hits[:10]}; forbidden_terms={forbidden[:6]}"
    return score, rationale


def build_libraries() -> Dict[str, DeviceLibrary]:
    des_user_needs = [
        UserNeed("UN-DES-001", "Interventional cardiologists need a sterile coronary stent system deliverable through tortuous coronary anatomy."),
        UserNeed("UN-DES-002", "The treated coronary artery must remain scaffolded with acceptable acute recoil and long-term fatigue performance."),
        UserNeed("UN-DES-003", "The drug coating must remain adherent and release drug within a controlled therapeutic range."),
        UserNeed("UN-DES-004", "Patients must not be exposed to unacceptable particulate, thrombosis, restenosis, fracture, or hypersensitivity risks."),
    ]
    des_inputs = [
        DesignInput("DI-DES-001", "UN-DES-001", "crossing profile", "Defined in approved design specification from structured device database.", ["ISO 25539", "21 CFR 820.30"]),
        DesignInput("DI-DES-002", "UN-DES-001", "trackability", "Bench method and acceptance criteria from coronary stent delivery library.", ["ISO 25539", "IEC 62366-1"]),
        DesignInput("DI-DES-003", "UN-DES-001", "pushability", "Bench method and acceptance criteria from coronary stent delivery library.", ["ISO 25539"]),
        DesignInput("DI-DES-004", "UN-DES-002", "radial strength", "Approved coronary stent mechanical specification.", ["ISO 25539"]),
        DesignInput("DI-DES-005", "UN-DES-002", "recoil", "Approved coronary stent mechanical specification.", ["ISO 25539"]),
        DesignInput("DI-DES-006", "UN-DES-002", "foreshortening", "Approved coronary stent mechanical specification.", ["ISO 25539"]),
        DesignInput("DI-DES-007", "UN-DES-002", "fatigue resistance", "Approved coronary stent durability specification.", ["ISO 25539"]),
        DesignInput("DI-DES-008", "UN-DES-003", "coating adhesion", "Approved coating integrity specification.", ["ISO 25539", "ISO 10993"]),
        DesignInput("DI-DES-009", "UN-DES-003", "coating durability", "Approved coating durability specification.", ["ISO 25539"]),
        DesignInput("DI-DES-010", "UN-DES-003", "drug loading", "Approved drug content specification.", ["ISO 25539"]),
        DesignInput("DI-DES-011", "UN-DES-003", "release kinetics", "Approved release profile specification.", ["ISO 25539"]),
        DesignInput("DI-DES-012", "UN-DES-004", "particulate generation", "Approved particulate limit from device knowledge library.", ["ISO 25539", "ISO 10993"]),
    ]
    des_hazards = [
        Hazard("HZ-DES-001", "stent thrombosis", "Delayed endothelialization or flow disturbance", "Thrombus formation in treated vessel", "Myocardial infarction or death", "Validated coating, sizing, labeling, antiplatelet precautions", "Acceptable with clinical benefit-risk justification", "Benefit-risk depends on reduced restenosis and acceptable thrombosis rates."),
        Hazard("HZ-DES-002", "restenosis", "Insufficient radial support or drug delivery", "Re-narrowing of treated coronary artery", "Repeat revascularization", "Radial strength, drug loading, release kinetics controls", "Acceptable when verification and clinical evidence pass", "Reduced restenosis is primary therapeutic benefit."),
        Hazard("HZ-DES-003", "vessel perforation", "Oversizing or delivery trauma", "Coronary vessel injury", "Tamponade, emergency intervention", "Sizing matrix, tip design, IFU warnings, simulated use", "Acceptable with trained-user validation", "Residual risk balanced against revascularization benefit."),
        Hazard("HZ-DES-004", "embolization", "Stent dislodgement during delivery", "Device embolizes from intended lesion", "Ischemia, retrieval intervention", "Secure crimping, delivery retention testing", "Acceptable after retention verification", "Residual risk monitored post-market."),
        Hazard("HZ-DES-005", "coating delamination", "Coating adhesion failure", "Coating fragments detach in vasculature", "Embolic event, inflammation", "Coating adhesion/durability tests and particulate limits", "Acceptable after coating verification", "Controlled release benefit requires coating integrity."),
        Hazard("HZ-DES-006", "drug overdose", "Excess drug loading or burst release", "Local tissue drug exposure above specification", "Toxicity, delayed healing", "Drug content and release kinetics verification", "Acceptable after release testing", "Drug effect supports restenosis reduction."),
        Hazard("HZ-DES-007", "drug underdose", "Low drug content or poor release", "Insufficient tissue drug exposure", "Restenosis", "Drug loading and release controls", "Acceptable after lot release controls", "Therapeutic benefit depends on release profile."),
        Hazard("HZ-DES-008", "stent fracture", "Cyclic coronary loading", "Structural discontinuity in implanted stent", "Restenosis, thrombosis", "Fatigue and durability testing", "Acceptable after fatigue verification", "Scaffold benefit requires durability."),
        Hazard("HZ-DES-009", "nickel hypersensitivity", "Metal ion exposure", "Patient exposure to nickel-containing alloy", "Allergic response", "Materials characterization and labeling", "Acceptable with labeling and biocompatibility", "Residual risk communicated in IFU."),
    ]

    tavr_user_needs = [
        UserNeed("UN-TAVR-001", "Operators need a sterile transcatheter valve system deliverable to the native aortic annulus."),
        UserNeed("UN-TAVR-002", "Patients need restoration of aortic valve function with acceptable hemodynamics."),
        UserNeed("UN-TAVR-003", "The valve and delivery system must limit embolization, paravalvular leak, thrombosis, and structural deterioration."),
    ]
    tavr_inputs = [
        DesignInput("DI-TAVR-001", "UN-TAVR-001", "delivery profile", "Approved transcatheter valve delivery specification.", ["ISO 5840", "IEC 62366-1"]),
        DesignInput("DI-TAVR-002", "UN-TAVR-001", "deployment accuracy", "Validated deployment accuracy specification.", ["ISO 5840"]),
        DesignInput("DI-TAVR-003", "UN-TAVR-002", "effective orifice area", "Approved hemodynamic specification.", ["ISO 5840"]),
        DesignInput("DI-TAVR-004", "UN-TAVR-002", "transvalvular gradient", "Approved hemodynamic specification.", ["ISO 5840"]),
        DesignInput("DI-TAVR-005", "UN-TAVR-003", "frame fatigue durability", "Approved durability specification.", ["ISO 5840"]),
        DesignInput("DI-TAVR-006", "UN-TAVR-003", "leaflet durability", "Approved leaflet durability specification.", ["ISO 5840", "ISO 10993"]),
        DesignInput("DI-TAVR-007", "UN-TAVR-003", "paravalvular leak sealing", "Approved sealing performance specification.", ["ISO 5840"]),
    ]
    tavr_hazards = [
        Hazard("HZ-TAVR-001", "annular rupture", "Oversizing or excessive radial force", "Aortic annulus injury", "Death or emergency surgery", "Sizing algorithm, radial force limits, IFU warnings", "Acceptable with strict sizing controls", "Benefit-risk tied to less invasive valve replacement."),
        Hazard("HZ-TAVR-002", "coronary obstruction", "Valve frame or leaflet blocks coronary ostium", "Coronary perfusion compromised", "Myocardial infarction or death", "Anatomic screening and deployment controls", "Acceptable with screening requirements", "Residual risk justified for eligible patients."),
        Hazard("HZ-TAVR-003", "valve embolization", "Inadequate anchoring or deployment error", "Valve migrates after deployment", "Hemodynamic collapse", "Anchoring verification and simulated use", "Acceptable after validation", "Monitored through post-market surveillance."),
        Hazard("HZ-TAVR-004", "leaflet thrombosis", "Flow stagnation or material response", "Thrombus on valve leaflet", "Stroke, valve dysfunction", "Hemodynamic design, anticoagulation labeling", "Acceptable with clinical controls", "Residual risk balanced against stenosis treatment."),
        Hazard("HZ-TAVR-005", "paravalvular leak", "Incomplete annular seal", "Regurgitant flow around valve", "Heart failure, hemolysis", "Seal design and sizing validation", "Acceptable after leak testing", "Benefit-risk depends on leak reduction."),
        Hazard("HZ-TAVR-006", "stroke", "Debris embolization during delivery", "Cerebral embolic event", "Neurologic injury or death", "Delivery controls, user training, clinical evaluation", "Acceptable with validated procedure", "Residual risk disclosed and monitored."),
    ]

    ptca_user_needs = [
        UserNeed("UN-PTCA-001", "Operators need a sterile coronary balloon catheter that reaches and dilates target stenoses."),
        UserNeed("UN-PTCA-002", "The balloon must inflate, deflate, and withstand rated burst pressure without unacceptable vessel trauma."),
    ]
    ptca_inputs = [
        DesignInput("DI-PTCA-001", "UN-PTCA-001", "crossing profile", "Approved PTCA catheter specification.", ["ISO 10555", "ISO 25539"]),
        DesignInput("DI-PTCA-002", "UN-PTCA-001", "trackability", "Approved PTCA catheter specification.", ["ISO 10555"]),
        DesignInput("DI-PTCA-003", "UN-PTCA-002", "rated burst pressure", "Approved balloon pressure specification.", ["ISO 10555"]),
        DesignInput("DI-PTCA-004", "UN-PTCA-002", "balloon compliance", "Approved balloon compliance chart.", ["ISO 10555"]),
        DesignInput("DI-PTCA-005", "UN-PTCA-002", "deflation time", "Approved catheter performance specification.", ["ISO 10555"]),
    ]
    ptca_hazards = [
        Hazard("HZ-PTCA-001", "balloon rupture", "Inflation above rated burst pressure", "Balloon ruptures in coronary artery", "Vessel injury or embolic fragments", "Rated burst pressure testing and labeling", "Acceptable after verification", "Angioplasty benefit requires controlled inflation."),
        Hazard("HZ-PTCA-002", "vessel dissection", "Over-dilation or mechanical trauma", "Coronary wall injury", "Ischemia, bailout stenting", "Sizing chart, compliance validation, IFU warnings", "Acceptable with user controls", "Residual risk known for PTCA procedure."),
        Hazard("HZ-PTCA-003", "failure to deflate", "Catheter lumen obstruction", "Balloon remains inflated", "Prolonged ischemia", "Deflation time and kink testing", "Acceptable after verification", "Residual risk controlled by emergency instructions."),
    ]

    suture_user_needs = [
        UserNeed("UN-SUT-001", "Surgeons need a sterile suture that approximates tissue with predictable tensile performance."),
        UserNeed("UN-SUT-002", "The needle-suture combination must pass through tissue and maintain attachment strength."),
    ]
    suture_inputs = [
        DesignInput("DI-SUT-001", "UN-SUT-001", "suture diameter", "USP/EP size specification from structured library.", ["ISO 10993", "ISO 13485"]),
        DesignInput("DI-SUT-002", "UN-SUT-001", "knot strength", "Approved tensile specification.", ["ISO 10993"]),
        DesignInput("DI-SUT-003", "UN-SUT-002", "needle attachment", "Approved needle attachment specification.", ["ISO 10993"]),
    ]
    suture_hazards = [
        Hazard("HZ-SUT-001", "suture breakage", "Insufficient tensile strength", "Wound support lost", "Wound dehiscence", "Tensile and knot strength testing", "Acceptable after verification", "Benefit-risk supports tissue approximation."),
        Hazard("HZ-SUT-002", "needle detachment", "Needle-suture attachment failure", "Needle separates during use", "Retained foreign body or tissue trauma", "Needle attachment testing", "Acceptable after verification", "Residual risk controlled by inspection and training."),
    ]

    def outputs(inputs: Sequence[DesignInput], prefix: str) -> List[DesignOutput]:
        return [
            DesignOutput(f"DO-{prefix}-{idx:03d}", item.id, f"Controlled drawing/specification for {item.parameter}", "Structured device output library")
            for idx, item in enumerate(inputs, start=1)
        ]

    def verifications(inputs: Sequence[DesignInput], family_prefix: str, standard: str) -> List[VerificationMethod]:
        return [
            VerificationMethod(f"VER-{family_prefix}-{idx:03d}", item.id, f"Bench verification for {item.parameter}", item.acceptance_basis, standard)
            for idx, item in enumerate(inputs, start=1)
        ]

    def validations(inputs: Sequence[DesignInput], family_prefix: str) -> List[ValidationMethod]:
        return [
            ValidationMethod(f"VAL-{family_prefix}-{idx:03d}", item.id, f"Simulated-use or clinical validation linkage for {item.parameter}", "Validation protocol/report or retrieved clinical evidence")
            for idx, item in enumerate(inputs, start=1)
        ]

    return {
        "Drug Eluting Coronary Stent": DeviceLibrary(
            family="Drug Eluting Coronary Stent",
            category="Cardiovascular Implant",
            technology_type="Drug Eluting Stent",
            intended_use="Percutaneous treatment of coronary artery stenosis to improve luminal diameter and reduce restenosis.",
            default_risk_class="Class III",
            implantable=True,
            sterile=True,
            allowed_materials=["Cobalt Chromium", "PLLA", "Sirolimus", "Everolimus", "Zotarolimus", "Biolimus", "Stainless Steel", "Platinum Chromium"],
            user_needs=des_user_needs,
            design_inputs=des_inputs,
            verification_methods=verifications(des_inputs, "DES", "ISO 25539"),
            validation_methods=validations(des_inputs, "DES"),
            hazards=des_hazards,
            standards=["21 CFR 820.30", "FDA QMSR", "ISO 13485:2016", "ISO 14971:2019", "ISO 25539", "ISO 10993", "IEC 62366-1", "EU MDR 2017/745 Annex II", "EU MDR 2017/745 Annex III", "EU MDR 2017/745 Annex XIV"],
            regulations=["FDA 21 CFR 820.30", "FDA QMSR", "EU MDR 2017/745 Annex II", "EU MDR 2017/745 Annex III", "EU MDR 2017/745 Annex XIV"],
            guidance=["FDA coronary drug-eluting stent nonclinical and clinical considerations", "FDA biocompatibility guidance", "MDR clinical evaluation expectations"],
            product_codes=["NIQ", "NIP"],
            predicate_search_terms=["drug eluting coronary stent", "coronary stent sirolimus", "coronary stent everolimus"],
            clinical_search_terms=["drug eluting stent", "coronary", "restenosis", "stent thrombosis"],
            forbidden_terms=["suture", "needle", "orthopedic", "acl", "gynecology", "ophthalmology", "heart valve", "tavr", "transcatheter valve"],
            required_terms=["coronary", "stent", "drug", "eluting"],
        ),
        "Transcatheter Aortic Valve Replacement": DeviceLibrary(
            family="Transcatheter Aortic Valve Replacement",
            category="Cardiovascular Implant",
            technology_type="Transcatheter Heart Valve",
            intended_use="Percutaneous replacement of diseased native or prosthetic aortic valves.",
            default_risk_class="Class III",
            implantable=True,
            sterile=True,
            allowed_materials=["Nitinol", "Cobalt Chromium", "Bovine Pericardium", "Porcine Pericardium", "Polyester", "Stainless Steel"],
            user_needs=tavr_user_needs,
            design_inputs=tavr_inputs,
            verification_methods=verifications(tavr_inputs, "TAVR", "ISO 5840"),
            validation_methods=validations(tavr_inputs, "TAVR"),
            hazards=tavr_hazards,
            standards=["21 CFR 820.30", "FDA QMSR", "ISO 13485:2016", "ISO 14971:2019", "ISO 5840", "ISO 10993", "IEC 62366-1", "EU MDR 2017/745 Annex II", "EU MDR 2017/745 Annex III", "EU MDR 2017/745 Annex XIV"],
            regulations=["FDA 21 CFR 820.30", "FDA QMSR", "EU MDR 2017/745 Annex II", "EU MDR 2017/745 Annex III", "EU MDR 2017/745 Annex XIV"],
            guidance=["FDA heart valve investigational and marketing submission expectations", "MDR clinical evaluation expectations"],
            product_codes=["NPT"],
            predicate_search_terms=["transcatheter aortic valve", "transcatheter heart valve", "TAVR"],
            clinical_search_terms=["transcatheter aortic valve", "TAVR", "aortic stenosis", "paravalvular leak"],
            forbidden_terms=["suture", "needle", "drug eluting stent", "coronary stent", "orthopedic", "acl", "ophthalmology"],
            required_terms=["transcatheter", "aortic", "valve"],
        ),
        "PTCA Balloon Catheter": DeviceLibrary(
            family="PTCA Balloon Catheter",
            category="Cardiovascular Catheter",
            technology_type="Percutaneous Transluminal Coronary Angioplasty Balloon",
            intended_use="Percutaneous balloon dilation of coronary artery stenosis.",
            default_risk_class="Class II",
            implantable=False,
            sterile=True,
            allowed_materials=["Nylon", "Pebax", "Polyurethane", "PTFE", "Stainless Steel", "Platinum Iridium"],
            user_needs=ptca_user_needs,
            design_inputs=ptca_inputs,
            verification_methods=verifications(ptca_inputs, "PTCA", "ISO 10555"),
            validation_methods=validations(ptca_inputs, "PTCA"),
            hazards=ptca_hazards,
            standards=["21 CFR 820.30", "FDA QMSR", "ISO 13485:2016", "ISO 14971:2019", "ISO 10555", "ISO 25539", "ISO 10993", "IEC 62366-1", "EU MDR 2017/745 Annex II", "EU MDR 2017/745 Annex III"],
            regulations=["FDA 21 CFR 820.30", "FDA QMSR", "EU MDR 2017/745 Annex II", "EU MDR 2017/745 Annex III"],
            guidance=["FDA intravascular catheter expectations", "MDR technical documentation expectations"],
            product_codes=["LOX"],
            predicate_search_terms=["PTCA balloon catheter", "coronary dilatation catheter"],
            clinical_search_terms=["PTCA balloon catheter", "coronary angioplasty", "balloon catheter"],
            forbidden_terms=["suture", "needle", "heart valve", "TAVR", "drug eluting stent", "orthopedic"],
            required_terms=["balloon", "catheter", "coronary"],
        ),
        "Suture": DeviceLibrary(
            family="Suture",
            category="Surgical Implant",
            technology_type="Absorbable or Non-absorbable Surgical Suture",
            intended_use="Approximation or ligation of soft tissue.",
            default_risk_class="Class II",
            implantable=True,
            sterile=True,
            allowed_materials=["Polypropylene", "Polydioxanone", "Poliglecaprone", "Nylon", "Silk", "Stainless Steel"],
            user_needs=suture_user_needs,
            design_inputs=suture_inputs,
            verification_methods=verifications(suture_inputs, "SUT", "USP/EP"),
            validation_methods=validations(suture_inputs, "SUT"),
            hazards=suture_hazards,
            standards=["21 CFR 820.30", "FDA QMSR", "ISO 13485:2016", "ISO 14971:2019", "ISO 10993", "IEC 62366-1", "EU MDR 2017/745 Annex II", "EU MDR 2017/745 Annex III"],
            regulations=["FDA 21 CFR 820.30", "FDA QMSR", "EU MDR 2017/745 Annex II", "EU MDR 2017/745 Annex III"],
            guidance=["FDA surgical suture special controls where applicable", "MDR technical documentation expectations"],
            product_codes=["GAM", "GAR", "NEW"],
            predicate_search_terms=["surgical suture", "absorbable suture"],
            clinical_search_terms=["surgical suture", "knot strength", "wound closure"],
            forbidden_terms=["drug eluting stent", "coronary", "TAVR", "heart valve", "balloon catheter"],
            required_terms=["suture"],
        ),
    }


DEVICE_LIBRARIES = build_libraries()


DEVICE_ALIASES: Dict[str, Dict[str, Any]] = {
    "biomime des": {
        "family": "Drug Eluting Coronary Stent",
        "manufacturer": "Meril Life Sciences",
        "materials": ["Cobalt Chromium", "PLLA", "Sirolimus"],
        "markets": ["US", "EU", "India"],
        "confidence": 0.98,
    },
    "xience": {
        "family": "Drug Eluting Coronary Stent",
        "manufacturer": "Abbott",
        "materials": ["Cobalt Chromium", "Everolimus"],
        "markets": ["US", "EU"],
        "confidence": 0.98,
    },
    "resolute onyx": {
        "family": "Drug Eluting Coronary Stent",
        "manufacturer": "Medtronic",
        "materials": ["Cobalt Chromium", "Zotarolimus"],
        "markets": ["US", "EU"],
        "confidence": 0.98,
    },
    "orsiro": {
        "family": "Drug Eluting Coronary Stent",
        "manufacturer": "Biotronik",
        "materials": ["Cobalt Chromium", "Sirolimus"],
        "markets": ["US", "EU"],
        "confidence": 0.98,
    },
    "sapien": {
        "family": "Transcatheter Aortic Valve Replacement",
        "manufacturer": "Edwards Lifesciences",
        "materials": ["Cobalt Chromium", "Bovine Pericardium"],
        "markets": ["US", "EU"],
        "confidence": 0.98,
    },
    "evolut": {
        "family": "Transcatheter Aortic Valve Replacement",
        "manufacturer": "Medtronic",
        "materials": ["Nitinol", "Porcine Pericardium"],
        "markets": ["US", "EU"],
        "confidence": 0.98,
    },
    "trek balloon": {
        "family": "PTCA Balloon Catheter",
        "manufacturer": "Abbott",
        "materials": ["Nylon", "Pebax"],
        "markets": ["US", "EU"],
        "confidence": 0.97,
    },
    "prolene": {
        "family": "Suture",
        "manufacturer": "Ethicon",
        "materials": ["Polypropylene"],
        "markets": ["US", "EU"],
        "confidence": 0.98,
    },
}


def resolve_device_profile(product_name: str, company_name: str, allow_public_lookup: bool = True) -> DeviceProfile:
    product_norm = normalize(product_name)
    company_norm = normalize(company_name)
    sources: List[str] = []

    for alias, config in DEVICE_ALIASES.items():
        if alias in product_norm:
            library = DEVICE_LIBRARIES[config["family"]]
            confidence = float(config["confidence"])
            if company_name and normalize(config["manufacturer"]) != company_norm:
                confidence -= 0.03
            sources.append(f"curated_alias:{alias}")
            return DeviceProfile(
                device_name=product_name,
                manufacturer=company_name or config["manufacturer"],
                device_category=library.category,
                device_family=library.family,
                intended_use=library.intended_use,
                technology_type=library.technology_type,
                risk_class=library.default_risk_class,
                implantable=library.implantable,
                sterile=library.sterile,
                materials=config["materials"],
                markets=config["markets"],
                confidence=round(confidence, 3),
                identity_sources=sources,
            )

    if allow_public_lookup:
        public_family, public_confidence, public_sources = classify_from_openfda(product_name, company_name)
        if public_family:
            library = DEVICE_LIBRARIES[public_family]
            sources.extend(public_sources)
            return DeviceProfile(
                device_name=product_name,
                manufacturer=company_name,
                device_category=library.category,
                device_family=library.family,
                intended_use=library.intended_use,
                technology_type=library.technology_type,
                risk_class=library.default_risk_class,
                implantable=library.implantable,
                sterile=library.sterile,
                materials=[],
                markets=["US"],
                confidence=round(public_confidence, 3),
                identity_sources=sources,
            )

    # Keyword fallback is intentionally below 95% so it documents likely family
    # without allowing DHF generation from name inference alone.
    keyword_family = classify_from_keywords(product_name)
    if keyword_family:
        library = DEVICE_LIBRARIES[keyword_family]
        return DeviceProfile(
            device_name=product_name,
            manufacturer=company_name,
            device_category=library.category,
            device_family=library.family,
            intended_use=library.intended_use,
            technology_type=library.technology_type,
            risk_class=library.default_risk_class,
            implantable=library.implantable,
            sterile=library.sterile,
            materials=[],
            markets=[],
            confidence=0.89,
            identity_sources=["keyword_only_low_confidence"],
        )

    raise DHFGenerationError(f"Unable to classify device from structured sources: {product_name!r}")


def classify_from_keywords(product_name: str) -> Optional[str]:
    value = normalize(product_name)
    if "drug eluting stent" in value or ("des" in value.split() and "stent" in value):
        return "Drug Eluting Coronary Stent"
    if "tavr" in value or "transcatheter aortic valve" in value or "heart valve" in value:
        return "Transcatheter Aortic Valve Replacement"
    if "ptca" in value or ("balloon" in value and "catheter" in value):
        return "PTCA Balloon Catheter"
    if "suture" in value:
        return "Suture"
    return None


def classify_from_openfda(product_name: str, company_name: str) -> Tuple[Optional[str], float, List[str]]:
    query = urllib.parse.quote(f'openfda.device_name:"{product_name}"')
    url = f"https://api.fda.gov/device/510k.json?search={query}&limit=5"
    data = safe_get_json(url)
    sources: List[str] = []
    if not data or not data.get("results"):
        return None, 0.0, sources

    best_family: Optional[str] = None
    best_score = 0.0
    for result in data.get("results", []):
        text = " ".join(str(result.get(key, "")) for key in ("device_name", "applicant", "product_code", "statement_or_summary"))
        family = classify_from_keywords(text)
        if not family:
            for library in DEVICE_LIBRARIES.values():
                if result.get("product_code") in library.product_codes:
                    family = library.family
                    break
        if not family:
            continue
        score = 0.9
        if normalize(product_name) in normalize(text):
            score += 0.04
        if company_name and normalize(company_name) in normalize(text):
            score += 0.04
        if score > best_score:
            best_family = family
            best_score = min(score, 0.98)
            sources = [f"openFDA_510k:{result.get('k_number') or result.get('pma_number') or result.get('product_code')}"]
    return best_family, best_score, sources


def validate_device_identity(profile: DeviceProfile) -> None:
    if profile.confidence < CONFIDENCE_THRESHOLD:
        raise DHFGenerationError(
            f"Device classification confidence {profile.confidence:.2f} is below {CONFIDENCE_THRESHOLD:.2f}. "
            "Generation rejected because product/company-only inference is not enough for a regulatory DHF."
        )
    if profile.device_family not in DEVICE_LIBRARIES:
        raise DHFGenerationError(f"No structured device library exists for {profile.device_family!r}.")


def validate_device_family(profile: DeviceProfile, library: DeviceLibrary) -> None:
    if profile.device_category != library.category or profile.technology_type != library.technology_type:
        raise DHFGenerationError("Device profile conflicts with curated family library.")


def validate_risk_library(library: DeviceLibrary) -> None:
    if not library.hazards:
        raise DHFGenerationError(f"No risk library configured for {library.family}.")
    hazard_text = normalize(" ".join(h.hazard for h in library.hazards))
    for forbidden in library.forbidden_terms:
        if normalize(forbidden) in hazard_text:
            raise DHFGenerationError(f"Risk contamination detected in {library.family}: {forbidden!r}")


def validate_standards(library: DeviceLibrary) -> None:
    required = {"ISO 13485:2016", "ISO 14971:2019"}
    missing = sorted(required - set(library.standards))
    if missing:
        raise DHFGenerationError(f"Standards mapping incomplete for {library.family}: missing {missing}")
    standards_text = normalize(" ".join(library.standards))
    for forbidden in library.forbidden_terms:
        if normalize(forbidden) in standards_text:
            raise DHFGenerationError(f"Standards contamination detected: {forbidden!r}")


def validate_materials(profile: DeviceProfile, library: DeviceLibrary) -> None:
    unknown = [material for material in profile.materials if material not in library.allowed_materials]
    if unknown:
        raise DHFGenerationError(f"Material contamination detected for {library.family}: {unknown}")


def validate_traceability(traceability: List[Dict[str, str]], library: DeviceLibrary) -> None:
    design_inputs = {item.id for item in library.design_inputs}
    linked = {row["design_input_id"] for row in traceability}
    missing = sorted(design_inputs - linked)
    if missing:
        raise DHFGenerationError(f"Traceability incomplete; missing design inputs: {missing}")


def validate_clinical_relevance(evidence: Sequence[EvidenceRecord]) -> None:
    accepted = [record for record in evidence if record.decision == "accepted"]
    if not accepted:
        raise DHFGenerationError("No clinical evidence met the relevance threshold. DHF generation rejected.")


def build_traceability(library: DeviceLibrary, evidence: Sequence[EvidenceRecord]) -> List[Dict[str, str]]:
    outputs_by_input = {
        item.design_input_id: item
        for item in [
            DesignOutput(f"DO-{slug(library.family)[:8].upper()}-{idx:03d}", di.id, f"Controlled design output for {di.parameter}", "Structured DHF output registry")
            for idx, di in enumerate(library.design_inputs, start=1)
        ]
    }
    ver_by_input = {item.design_input_id: item for item in library.verification_methods}
    val_by_input = {item.design_input_id: item for item in library.validation_methods}
    first_evidence = next((item for item in evidence if item.decision == "accepted"), None)
    first_hazard = library.hazards[0]
    rows: List[Dict[str, str]] = []
    for item in library.design_inputs:
        rows.append(
            {
                "user_need_id": item.user_need_id,
                "design_input_id": item.id,
                "design_output_id": outputs_by_input[item.id].id,
                "verification_id": ver_by_input[item.id].id,
                "validation_id": val_by_input[item.id].id,
                "risk_control_id": first_hazard.id,
                "residual_risk": first_hazard.residual_risk,
                "clinical_evidence": first_evidence.identifier if first_evidence else "NONE",
                "regulatory_requirement": "; ".join(item.regulatory_basis),
            }
        )
    return rows


def pubmed_search(profile: DeviceProfile, library: DeviceLibrary, limit: int) -> List[EvidenceRecord]:
    terms = f'("{profile.device_name}" OR "{profile.device_family}" OR "{library.technology_type}") AND clinical'
    search_url = (
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?"
        + urllib.parse.urlencode({"db": "pubmed", "term": terms, "retmode": "json", "retmax": str(limit)}, quote_via=urllib.parse.quote)
    )
    search = safe_get_json(search_url)
    ids = (search or {}).get("esearchresult", {}).get("idlist", [])
    if not ids:
        return []
    summary_url = (
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?"
        + urllib.parse.urlencode({"db": "pubmed", "id": ",".join(ids), "retmode": "json"}, quote_via=urllib.parse.quote)
    )
    summary = safe_get_json(summary_url) or {}
    records: List[EvidenceRecord] = []
    for pmid in ids:
        item = summary.get("result", {}).get(pmid, {})
        title = item.get("title", "")
        year = str(item.get("pubdate", ""))[:4] or None
        score, rationale = score_relevance(title, library, profile)
        records.append(
            EvidenceRecord(
                source="PubMed",
                title=title,
                url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                identifier=f"PMID:{pmid}",
                year=year,
                relevance_score=round(score, 3),
                decision="accepted" if score >= CLINICAL_RELEVANCE_THRESHOLD else "rejected",
                rationale=rationale,
            )
        )
    return records


def europe_pmc_search(profile: DeviceProfile, library: DeviceLibrary, limit: int) -> List[EvidenceRecord]:
    query = f'"{profile.device_name}" OR "{profile.device_family}" OR "{library.technology_type}"'
    url = "https://www.ebi.ac.uk/europepmc/webservices/rest/search?" + urllib.parse.urlencode(
        {"query": query, "format": "json", "pageSize": str(limit)}, quote_via=urllib.parse.quote
    )
    data = safe_get_json(url) or {}
    records: List[EvidenceRecord] = []
    for item in data.get("resultList", {}).get("result", [])[:limit]:
        title = item.get("title", "")
        identifier = item.get("pmid") or item.get("pmcid") or item.get("doi") or item.get("id", "")
        url_value = f"https://europepmc.org/article/MED/{identifier}" if identifier else "https://europepmc.org/"
        score, rationale = score_relevance(title, library, profile)
        records.append(
            EvidenceRecord(
                source="Europe PMC",
                title=title,
                url=url_value,
                identifier=f"EPMC:{identifier}",
                year=item.get("pubYear"),
                relevance_score=round(score, 3),
                decision="accepted" if score >= CLINICAL_RELEVANCE_THRESHOLD else "rejected",
                rationale=rationale,
            )
        )
    return records


def clinical_trials_search(profile: DeviceProfile, library: DeviceLibrary, limit: int) -> List[EvidenceRecord]:
    query = f'{profile.device_name} {profile.device_family}'
    url = "https://clinicaltrials.gov/api/v2/studies?" + urllib.parse.urlencode(
        {"query.term": query, "pageSize": str(limit), "format": "json"}, quote_via=urllib.parse.quote
    )
    data = safe_get_json(url) or {}
    records: List[EvidenceRecord] = []
    for study in data.get("studies", [])[:limit]:
        protocol = study.get("protocolSection", {})
        identification = protocol.get("identificationModule", {})
        status = protocol.get("statusModule", {})
        title = identification.get("briefTitle", "")
        nct_id = identification.get("nctId", "")
        start_date = status.get("startDateStruct", {}).get("date", "")
        score, rationale = score_relevance(title, library, profile)
        records.append(
            EvidenceRecord(
                source="ClinicalTrials.gov",
                title=title,
                url=f"https://clinicaltrials.gov/study/{nct_id}" if nct_id else "https://clinicaltrials.gov/",
                identifier=nct_id,
                year=start_date[:4] if start_date else None,
                relevance_score=round(score, 3),
                decision="accepted" if score >= CLINICAL_RELEVANCE_THRESHOLD else "rejected",
                rationale=rationale,
            )
        )
    return records


def retrieve_clinical_evidence(profile: DeviceProfile, library: DeviceLibrary, limit_per_source: int = 5) -> List[EvidenceRecord]:
    records: List[EvidenceRecord] = []
    for fetcher in (pubmed_search, europe_pmc_search, clinical_trials_search):
        records.extend(fetcher(profile, library, limit_per_source))
        time.sleep(0.15)
    records.sort(key=lambda item: item.relevance_score, reverse=True)
    return records


def retrieve_predicates(profile: DeviceProfile, library: DeviceLibrary, limit: int = 8) -> List[PredicateRecord]:
    records: List[PredicateRecord] = []
    family_terms = tokenize(library.family + " " + library.technology_type + " " + " ".join(library.required_terms))

    def score_record(result: Dict[str, Any], source: str) -> PredicateRecord:
        text = " ".join(
            str(result.get(key, ""))
            for key in (
                "device_name",
                "trade_name",
                "generic_name",
                "applicant",
                "product_code",
                "statement_or_summary",
                "ao_statement",
            )
        )
        text_terms = tokenize(text)
        product_code = result.get("product_code", "")
        score = len(family_terms & text_terms) / max(1, len(family_terms))
        if product_code in library.product_codes:
            score += 0.35
        if any(normalize(term) in normalize(text) for term in library.predicate_search_terms):
            score += 0.25
        score = min(score, 1.0)
        return PredicateRecord(
            source=source,
            device_name=result.get("device_name") or result.get("trade_name") or result.get("generic_name", ""),
            applicant=result.get("applicant", ""),
            identifier=result.get("k_number") or result.get("pma_number", ""),
            product_code=product_code,
            decision_date=result.get("decision_date", ""),
            compatibility_score=round(score, 3),
            decision="accepted" if score >= 0.75 else "rejected",
            rationale=f"product_code={product_code}; compatible_codes={library.product_codes}; family_term_overlap={round(score, 3)}",
        )

    endpoints = [
        ("openFDA 510(k)", "https://api.fda.gov/device/510k.json"),
        ("openFDA PMA", "https://api.fda.gov/device/pma.json"),
    ]
    seen: set[Tuple[str, str]] = set()
    for source, endpoint in endpoints:
        for term in library.predicate_search_terms:
            url = endpoint + "?" + urllib.parse.urlencode({"search": f'"{term}"', "limit": str(limit)}, quote_via=urllib.parse.quote)
            data = safe_get_json(url) or {}
            for result in data.get("results", [])[:limit]:
                record = score_record(result, source)
                key = (record.source, record.identifier)
                if key in seen:
                    continue
                seen.add(key)
                records.append(record)

    records.sort(key=lambda item: item.compatibility_score, reverse=True)
    return records


def validate_predicates(predicates: Sequence[PredicateRecord]) -> None:
    if not any(item.decision == "accepted" for item in predicates):
        raise DHFGenerationError("No compatible predicate records found from deterministic product-code/family checks.")


def make_fmea(library: DeviceLibrary) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for idx, hazard in enumerate(library.hazards, start=1):
        severity = 4 if any(term in normalize(hazard.harm) for term in ("death", "myocardial", "stroke")) else 3
        occurrence = 2
        detectability = 2
        rpn = severity * occurrence * detectability
        rows.append(
            {
                "id": hazard.id,
                "hazard": hazard.hazard,
                "foreseeable_sequence": hazard.foreseeable_sequence,
                "hazardous_situation": hazard.hazardous_situation,
                "harm": hazard.harm,
                "initial_severity": severity,
                "initial_occurrence": occurrence,
                "detectability": detectability,
                "initial_rpn": rpn,
                "risk_control": hazard.risk_control,
                "residual_risk": hazard.residual_risk,
                "benefit_risk": hazard.benefit_risk,
                "acceptability_decision": "acceptable with controls" if rpn <= 16 else "requires SME review",
            }
        )
    return rows


def run_quality_gates(
    profile: DeviceProfile,
    library: DeviceLibrary,
    evidence: Sequence[EvidenceRecord],
    predicates: Sequence[PredicateRecord],
    traceability: List[Dict[str, str]],
) -> List[str]:
    gates = [
        ("validate_device_identity", lambda: validate_device_identity(profile)),
        ("validate_device_family", lambda: validate_device_family(profile, library)),
        ("validate_risk_library", lambda: validate_risk_library(library)),
        ("validate_standards", lambda: validate_standards(library)),
        ("validate_materials", lambda: validate_materials(profile, library)),
        ("validate_predicates", lambda: validate_predicates(predicates)),
        ("validate_traceability", lambda: validate_traceability(traceability, library)),
        ("validate_clinical_relevance", lambda: validate_clinical_relevance(evidence)),
    ]
    passed: List[str] = []
    for name, fn in gates:
        fn()
        passed.append(name)
    return passed


def assemble_dhf(product_name: str, company_name: str, allow_public_lookup: bool = True) -> Dict[str, Any]:
    profile = resolve_device_profile(product_name, company_name, allow_public_lookup=allow_public_lookup)
    validate_device_identity(profile)
    library = DEVICE_LIBRARIES[profile.device_family]
    evidence = retrieve_clinical_evidence(profile, library)
    predicates = retrieve_predicates(profile, library)
    traceability = build_traceability(library, evidence)
    passed_gates = run_quality_gates(profile, library, evidence, predicates, traceability)

    accepted_evidence = [dataclasses.asdict(item) for item in evidence if item.decision == "accepted"]
    rejected_evidence = [dataclasses.asdict(item) for item in evidence if item.decision == "rejected"]
    accepted_predicates = [dataclasses.asdict(item) for item in predicates if item.decision == "accepted"]
    rejected_predicates = [dataclasses.asdict(item) for item in predicates if item.decision == "rejected"]

    return {
        "metadata": {
            "generated_at": dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "system": "Regulatory knowledge system with DHF rendering layer",
            "llm_policy": "LLM may summarize, organize, format, and explain only; engineering facts are sourced from structured libraries and public retrieval.",
            "quality_gates_passed": passed_gates,
        },
        "device_profile": dataclasses.asdict(profile),
        "design_and_development_plan": {
            "scope": f"DHF package for {profile.device_name} ({profile.device_family}).",
            "applicable_regulations": library.regulations,
            "standards_strategy": library.standards,
            "design_review_records": [
                {"id": "DR-001", "phase": "Planning", "required_inputs": ["Device identity", "intended use", "markets", "risk class"]},
                {"id": "DR-002", "phase": "Design input freeze", "required_inputs": [item.id for item in library.design_inputs]},
                {"id": "DR-003", "phase": "Verification readiness", "required_inputs": [item.id for item in library.verification_methods]},
                {"id": "DR-004", "phase": "Validation and release", "required_inputs": [item.id for item in library.validation_methods]},
            ],
            "change_control_records": [
                {"id": "CC-001", "trigger": "Design input change", "required_assessment": "Risk, verification, validation, standards, clinical evidence impact"},
                {"id": "CC-002", "trigger": "Material/process/supplier change", "required_assessment": "Biocompatibility, sterilization, performance, regulatory impact"},
            ],
        },
        "user_needs": [dataclasses.asdict(item) for item in library.user_needs],
        "design_inputs": [dataclasses.asdict(item) for item in library.design_inputs],
        "design_outputs": [
            dataclasses.asdict(
                DesignOutput(
                    f"DO-{slug(library.family)[:8].upper()}-{idx:03d}",
                    item.id,
                    f"Controlled design output for {item.parameter}",
                    "Structured DHF output registry",
                )
            )
            for idx, item in enumerate(library.design_inputs, start=1)
        ],
        "design_verification": [dataclasses.asdict(item) for item in library.verification_methods],
        "design_validation": [dataclasses.asdict(item) for item in library.validation_methods],
        "risk_management_file": {
            "standard": "ISO 14971:2019",
            "hazards": [dataclasses.asdict(item) for item in library.hazards],
            "fmea": make_fmea(library),
            "residual_risk_summary": "Residual risks are acceptable only after all listed controls are verified and reviewed by qualified SMEs.",
        },
        "clinical_evidence_summary": {
            "accepted": accepted_evidence,
            "rejected": rejected_evidence,
            "threshold": CLINICAL_RELEVANCE_THRESHOLD,
        },
        "regulatory_strategy": {
            "risk_class": profile.risk_class,
            "markets": profile.markets,
            "regulations": library.regulations,
            "guidance": library.guidance,
            "submission_note": "Regulatory pathway requires SME confirmation against current jurisdiction-specific rules before submission.",
        },
        "predicate_analysis": {
            "accepted": accepted_predicates,
            "rejected": rejected_predicates,
            "compatibility_rule": "Predicate must match curated device family terms and accepted product code mappings.",
        },
        "standards_matrix": [{"standard": standard, "applicability": "applicable by curated device-family mapping"} for standard in library.standards],
        "traceability_matrix": traceability,
        "verification_reports": [
            {"verification_id": item.id, "status": "protocol required", "method": item.method, "acceptance_basis": item.acceptance_basis}
            for item in library.verification_methods
        ],
        "validation_reports": [
            {"validation_id": item.id, "status": "protocol/report or clinical evidence required", "method": item.method, "evidence_type": item.evidence_type}
            for item in library.validation_methods
        ],
    }


def render_table(headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
    out = ["<table>", "<thead><tr>"]
    out.extend(f"<th>{html.escape(str(header))}</th>" for header in headers)
    out.append("</tr></thead><tbody>")
    for row in rows:
        out.append("<tr>")
        out.extend(f"<td>{html.escape(str(cell))}</td>" for cell in row)
        out.append("</tr>")
    out.append("</tbody></table>")
    return "\n".join(out)


def render_html(report: Dict[str, Any]) -> str:
    profile = report["device_profile"]
    style = """
    body{font-family:Arial,Helvetica,sans-serif;color:#111827;line-height:1.45;margin:32px;}
    h1{font-size:28px;margin-bottom:4px;} h2{font-size:20px;border-bottom:1px solid #d1d5db;padding-bottom:4px;margin-top:28px;}
    h3{font-size:16px;margin-top:18px;} table{border-collapse:collapse;width:100%;font-size:12px;margin:12px 0;}
    th,td{border:1px solid #d1d5db;padding:6px;text-align:left;vertical-align:top;} th{background:#f3f4f6;}
    .small{font-size:12px;color:#4b5563}.gate{display:inline-block;border:1px solid #9ca3af;padding:2px 6px;margin:2px;border-radius:3px;}
    """
    parts = [
        "<!doctype html><html><head><meta charset='utf-8'>",
        f"<title>DHF - {html.escape(profile['device_name'])}</title>",
        f"<style>{style}</style></head><body>",
        f"<h1>Design History File: {html.escape(profile['device_name'])}</h1>",
        f"<div class='small'>Manufacturer: {html.escape(profile['manufacturer'])} | Generated: {html.escape(report['metadata']['generated_at'])}</div>",
        "<h2>Quality Gates</h2>",
        "".join(f"<span class='gate'>{html.escape(gate)}</span>" for gate in report["metadata"]["quality_gates_passed"]),
        "<h2>Device Profile</h2>",
        render_table(["Field", "Value"], [[key, json.dumps(value) if isinstance(value, list) else value] for key, value in profile.items()]),
        "<h2>Design and Development Plan</h2>",
        f"<p>{html.escape(report['design_and_development_plan']['scope'])}</p>",
        "<h2>User Needs</h2>",
        render_table(["ID", "Statement"], [[item["id"], item["statement"]] for item in report["user_needs"]]),
        "<h2>Design Inputs</h2>",
        render_table(["ID", "User Need", "Parameter", "Acceptance Basis", "Regulatory Basis"], [[item["id"], item["user_need_id"], item["parameter"], item["acceptance_basis"], "; ".join(item["regulatory_basis"])] for item in report["design_inputs"]]),
        "<h2>Design Outputs</h2>",
        render_table(["ID", "Design Input", "Artifact", "Source"], [[item["id"], item["design_input_id"], item["artifact"], item["source"]] for item in report["design_outputs"]]),
        "<h2>Verification</h2>",
        render_table(["ID", "Design Input", "Method", "Acceptance Basis", "Standard"], [[item["id"], item["design_input_id"], item["method"], item["acceptance_basis"], item["standard"]] for item in report["design_verification"]]),
        "<h2>Validation</h2>",
        render_table(["ID", "Design Input", "Method", "Evidence Type"], [[item["id"], item["design_input_id"], item["method"], item["evidence_type"]] for item in report["design_validation"]]),
        "<h2>Risk Management File</h2>",
        render_table(["ID", "Hazard", "Sequence", "Hazardous Situation", "Harm", "Control", "Residual Risk"], [[item["id"], item["hazard"], item["foreseeable_sequence"], item["hazardous_situation"], item["harm"], item["risk_control"], item["residual_risk"]] for item in report["risk_management_file"]["hazards"]]),
        "<h2>FMEA</h2>",
        render_table(["ID", "Hazard", "S", "O", "D", "RPN", "Decision"], [[item["id"], item["hazard"], item["initial_severity"], item["initial_occurrence"], item["detectability"], item["initial_rpn"], item["acceptability_decision"]] for item in report["risk_management_file"]["fmea"]]),
        "<h2>Clinical Evidence Summary</h2>",
        "<h3>Accepted</h3>",
        render_table(["Source", "Identifier", "Year", "Score", "Title", "URL", "Rationale"], [[item["source"], item["identifier"], item["year"], item["relevance_score"], item["title"], item["url"], item["rationale"]] for item in report["clinical_evidence_summary"]["accepted"]]),
        "<h3>Rejected</h3>",
        render_table(["Source", "Identifier", "Score", "Title", "Rationale"], [[item["source"], item["identifier"], item["relevance_score"], item["title"], item["rationale"]] for item in report["clinical_evidence_summary"]["rejected"]]),
        "<h2>Predicate Analysis</h2>",
        render_table(["Source", "Identifier", "Product Code", "Score", "Device", "Applicant", "Decision", "Rationale"], [[item["source"], item["identifier"], item["product_code"], item["compatibility_score"], item["device_name"], item["applicant"], item["decision"], item["rationale"]] for item in report["predicate_analysis"]["accepted"] + report["predicate_analysis"]["rejected"]]),
        "<h2>Standards Matrix</h2>",
        render_table(["Standard", "Applicability"], [[item["standard"], item["applicability"]] for item in report["standards_matrix"]]),
        "<h2>Traceability Matrix</h2>",
        render_table(["User Need", "Design Input", "Design Output", "Verification", "Validation", "Risk Control", "Residual Risk", "Clinical Evidence", "Regulatory Requirement"], [[row["user_need_id"], row["design_input_id"], row["design_output_id"], row["verification_id"], row["validation_id"], row["risk_control_id"], row["residual_risk"], row["clinical_evidence"], row["regulatory_requirement"]] for row in report["traceability_matrix"]]),
        "<h2>Regulatory Strategy</h2>",
        render_table(["Field", "Value"], [[key, json.dumps(value) if isinstance(value, list) else value] for key, value in report["regulatory_strategy"].items()]),
        "<p class='small'>This DHF is pre-SME review. It is designed to prevent cross-device contamination and hallucinated engineering facts, not to replace regulatory sign-off.</p>",
        "</body></html>",
    ]
    return "\n".join(parts)


def render_pdf_if_available(report: Dict[str, Any], output_path: Path) -> bool:
    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
        from reportlab.lib import colors
    except Exception:
        return False

    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(str(output_path), pagesize=letter)
    story: List[Any] = []
    profile = report["device_profile"]
    story.append(Paragraph(f"Design History File: {profile['device_name']}", styles["Title"]))
    story.append(Paragraph(f"Manufacturer: {profile['manufacturer']}", styles["Normal"]))
    story.append(Paragraph(f"Generated: {report['metadata']['generated_at']}", styles["Normal"]))
    story.append(Spacer(1, 12))

    def add_heading(text: str) -> None:
        story.append(Spacer(1, 8))
        story.append(Paragraph(text, styles["Heading2"]))

    def add_table(headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> None:
        data = [list(headers)] + [[str(cell) for cell in row] for row in rows]
        table = Table(data, repeatRows=1)
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                    ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("FONTSIZE", (0, 0), (-1, -1), 7),
                ]
            )
        )
        story.append(table)

    add_heading("Device Profile")
    add_table(["Field", "Value"], [[key, json.dumps(value) if isinstance(value, list) else value] for key, value in profile.items()])
    add_heading("Design Inputs")
    add_table(["ID", "Parameter", "Basis"], [[item["id"], item["parameter"], item["acceptance_basis"]] for item in report["design_inputs"]])
    add_heading("Risk Management")
    add_table(["ID", "Hazard", "Control", "Residual Risk"], [[item["id"], item["hazard"], item["risk_control"], item["residual_risk"]] for item in report["risk_management_file"]["hazards"]])
    add_heading("Clinical Evidence")
    add_table(["Source", "ID", "Score", "Title"], [[item["source"], item["identifier"], item["relevance_score"], item["title"]] for item in report["clinical_evidence_summary"]["accepted"]])
    add_heading("Traceability")
    add_table(["UN", "DI", "DO", "VER", "VAL", "Risk", "Clinical"], [[row["user_need_id"], row["design_input_id"], row["design_output_id"], row["verification_id"], row["validation_id"], row["risk_control_id"], row["clinical_evidence"]] for row in report["traceability_matrix"]])
    doc.build(story)
    return True


def pdf_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def render_basic_pdf(report: Dict[str, Any], output_path: Path) -> None:
    """Write a dependency-free text PDF fallback.

    This keeps the "Final DHF PDF" artifact available in locked-down runtime
    environments. Install reportlab for the richer tabular PDF renderer.
    """
    profile = report["device_profile"]
    lines = [
        f"Design History File: {profile['device_name']}",
        f"Manufacturer: {profile['manufacturer']}",
        f"Generated: {report['metadata']['generated_at']}",
        "",
        "Quality Gates:",
        *[f"- {gate}" for gate in report["metadata"]["quality_gates_passed"]],
        "",
        "Device Profile:",
        f"- Family: {profile['device_family']}",
        f"- Category: {profile['device_category']}",
        f"- Technology: {profile['technology_type']}",
        f"- Risk class: {profile['risk_class']}",
        f"- Materials: {', '.join(profile['materials']) or 'Not populated by source'}",
        "",
        "Design Inputs:",
        *[f"- {item['id']}: {item['parameter']} | {item['acceptance_basis']}" for item in report["design_inputs"]],
        "",
        "Risk Management:",
        *[f"- {item['id']}: {item['hazard']} | Control: {item['risk_control']}" for item in report["risk_management_file"]["hazards"]],
        "",
        "Accepted Clinical Evidence:",
        *[
            f"- {item['identifier']} ({item['source']}, score {item['relevance_score']}): {item['title']}"
            for item in report["clinical_evidence_summary"]["accepted"]
        ],
        "",
        "Accepted Predicate/Comparator Records:",
        *[
            f"- {item['identifier']} {item['device_name']} | Product code {item['product_code']} | Score {item['compatibility_score']}"
            for item in report["predicate_analysis"]["accepted"]
        ],
        "",
        "Traceability:",
        *[
            f"- {row['user_need_id']} -> {row['design_input_id']} -> {row['design_output_id']} -> {row['verification_id']} -> {row['validation_id']} -> {row['risk_control_id']}"
            for row in report["traceability_matrix"]
        ],
        "",
        "Note: This fallback PDF is a text rendering of the gated DHF package. The JSON and HTML outputs contain the complete structured tables.",
    ]

    wrapped: List[str] = []
    for line in lines:
        wrapped.extend(textwrap.wrap(line, width=96) or [""])

    pages = [wrapped[idx : idx + 52] for idx in range(0, len(wrapped), 52)] or [[]]
    objects: List[str] = []
    page_refs: List[int] = []

    objects.append("<< /Type /Catalog /Pages 2 0 R >>")
    objects.append("<< /Type /Pages /Kids [] /Count 0 >>")
    font_obj = len(objects) + 1
    objects.append("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    for page in pages:
        stream_lines = ["BT", "/F1 9 Tf", "50 760 Td", "12 TL"]
        for line in page:
            stream_lines.append(f"({pdf_escape(line)}) Tj")
            stream_lines.append("T*")
        stream_lines.append("ET")
        stream = "\n".join(stream_lines)
        content_obj = len(objects) + 1
        objects.append(f"<< /Length {len(stream.encode('latin-1', errors='replace'))} >>\nstream\n{stream}\nendstream")
        page_obj = len(objects) + 1
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 {font_obj} 0 R >> >> /Contents {content_obj} 0 R >>"
        )
        page_refs.append(page_obj)

    objects[1] = f"<< /Type /Pages /Kids [{' '.join(f'{ref} 0 R' for ref in page_refs)}] /Count {len(page_refs)} >>"

    pdf = ["%PDF-1.4\n"]
    offsets = [0]
    for idx, obj in enumerate(objects, start=1):
        offsets.append(sum(len(part.encode("latin-1", errors="replace")) for part in pdf))
        pdf.append(f"{idx} 0 obj\n{obj}\nendobj\n")
    xref_offset = sum(len(part.encode("latin-1", errors="replace")) for part in pdf)
    pdf.append(f"xref\n0 {len(objects) + 1}\n")
    pdf.append("0000000000 65535 f \n")
    for offset in offsets[1:]:
        pdf.append(f"{offset:010d} 00000 n \n")
    pdf.append(f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n")
    output_path.write_bytes("".join(pdf).encode("latin-1", errors="replace"))


def write_outputs(report: Dict[str, Any], output_dir: Path) -> Dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    base = slug(f"{report['device_profile']['manufacturer']} {report['device_profile']['device_name']} dhf")
    json_path = output_dir / f"{base}.json"
    html_path = output_dir / f"{base}.html"
    pdf_path = output_dir / f"{base}.pdf"
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    html_path.write_text(render_html(report), encoding="utf-8")
    outputs = {"json": str(json_path), "html": str(html_path)}
    if render_pdf_if_available(report, pdf_path):
        outputs["pdf"] = str(pdf_path)
    else:
        render_basic_pdf(report, pdf_path)
        outputs["pdf"] = str(pdf_path)
    return outputs


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a gated DHF package from product and company name only.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent(
            """
            Examples:
              python server/dhf_report.py --product "BioMime DES" --company "Meril Life Sciences" --out /tmp/dhf
              python server/dhf_report.py --product "Evolut" --company "Medtronic" --out /tmp/dhf
            """
        ),
    )
    parser.add_argument("--product", required=True, help="Product/device name. This is the only device input field.")
    parser.add_argument("--company", required=True, help="Company/manufacturer name. This is the only manufacturer input field.")
    parser.add_argument("--out", default="dhf_output", help="Output directory for JSON/HTML/PDF files.")
    parser.add_argument("--offline", action="store_true", help="Disable public-source retrieval. Useful for testing gates.")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    try:
        report = assemble_dhf(args.product, args.company, allow_public_lookup=not args.offline)
        outputs = write_outputs(report, Path(args.out))
    except DHFGenerationError as exc:
        print(json.dumps({"success": False, "error": str(exc)}, indent=2), file=sys.stderr)
        return 2
    print(json.dumps({"success": True, "outputs": outputs}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

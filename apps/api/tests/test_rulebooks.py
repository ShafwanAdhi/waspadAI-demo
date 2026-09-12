import json

from scripts.compile_rulebooks import RULEBOOK_DIR, compile_rulebooks


def test_rulebooks_compile_and_preserve_rule_evidence_boundary(tmp_path):
    manifest = compile_rulebooks(tmp_path)

    assert manifest["rule_count"] >= 255
    assert manifest["source_count"] >= 18
    assert manifest["deterministic_trigger_count"] == 17
    assert manifest["separation_invariant"] == "RULE_CONTEXT_IS_NOT_EVIDENCE"
    assert {item["name"] for item in manifest["source_files"]} == {
        "rulebook_government_public_service.txt",
        "rulebook_impersonation_phishing_ato.txt",
        "rulebook_general_information_integrity.txt",
        "deterministic_triggers.json",
    }

    rules = [
        json.loads(line)
        for line in (tmp_path / "rules.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    by_id = {rule["id"]: rule for rule in rules}
    assert by_id["ATO-R004"]["trigger_description"] == "secret_request_detected=true"
    assert "case_is_scam" in by_id["ATO-R004"]["does_not_prove"]
    assert by_id["GOV-R010"]["caveat"].startswith("payment_requested=true saja")
    assert by_id["INF-R014"]["chunk_type"] == "decision_guidance"
    assert by_id["INF-R024"]["content"].startswith("Provenance yang tervalidasi")


def test_trigger_registry_references_canonical_rules():
    triggers = json.loads((RULEBOOK_DIR / "deterministic_triggers.json").read_text(encoding="utf-8"))
    government_payment = next(item for item in triggers if item["trigger_id"] == "GOV-DT003")

    assert government_payment["condition"]["all"][1]["field"] == "payment_requested"
    assert government_payment["force_rule_ids"] == ["GOV-R010", "GOV-R025"]

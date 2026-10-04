import json
import re

from tools.export_snapshot import NEEDS, build, render


def test_snapshot_is_built_from_the_same_data_as_the_site():
    data = build()
    assert data["meta"]["clinics"] == len(data["clinics"]) > 400
    assert len(data["doctors"]) == data["meta"]["doctors"]["total"]
    ids = {c["id"] for c in data["clinics"]}
    assert set(data["reviews"]) == ids
    for need in NEEDS:
        for variant in ("0", "1"):
            assert {i["id"] for i in data["recommend"][need][variant]["items"]} <= ids
    assert all(c["checks"] and c["level"] in ("good", "ok", "bad") for c in data["clinics"])


def test_render_embeds_data_and_survives_script_breaking_text():
    html = render({"note": "</script><script>alert(1)</script>", "clinics": []})
    assert "/*__DATA__*/" not in html and "<title>DentBishkek</title>" in html
    payload = re.search(r'<script type="application/json" id="data">(.*?)</script>', html, re.S).group(1)
    assert json.loads(payload)["note"].startswith("</script>")      # данные не закрывают тег раньше времени
    assert render({}, standalone=True).startswith("<!doctype html>")

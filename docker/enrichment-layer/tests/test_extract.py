from enrichment.extract import extract
from enrichment.fetch import FetchResult

SAMPLE_HTML = b"""
<html>
  <head><title>How to Export a PNG in Figma</title></head>
  <body>
    <h1>Export a PNG in Figma</h1>
    <ol>
      <li>Select the frame you want to export.</li>
      <li>Open the Export panel on the right.</li>
      <li>Click the plus button and choose PNG.</li>
      <li>Press the Export button to save the file.</li>
    </ol>
    <img src="step1.png" />
    <img src="step2.png" />
  </body>
</html>
"""


def test_extract_captures_features():
    fetch = FetchResult(
        url="https://example.com/figma-export",
        final_url="https://example.com/figma-export",
        http_status=200,
        html=SAMPLE_HTML,
        content_hash="abc123",
    )

    result = extract(fetch, application="Figma", goal="export PNG")

    assert result.title == "How to Export a PNG in Figma"
    assert result.text_length > 0
    assert result.ordered_list_items == 4
    assert result.image_count == 2
    assert result.imperative_verb_density > 0
    assert result.application_term_present is True
    assert result.goal_term_present is True

#!/usr/bin/env python3
"""Exercise the real frontend component with synthetic state, without browser network access."""
from pathlib import Path
import argparse
import json
import re
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--chromium', help='Optional system Chromium executable; otherwise use the Playwright browser')
    parser.add_argument('--output', type=Path, help='Optional directory for clearly labeled synthetic UI screenshots')
    args = parser.parse_args()
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        parser.error('Install the optional browser dependencies: pip install -e ".[browser]"; playwright install chromium')
    from opiha_apps.catalog import public_catalog
    html = (ROOT / 'examples/native-apps/panel-demo.html').read_text()
    script = re.search(r'<script type="module">(.*?)</script>', html, re.S).group(1)
    script = script.replace("import '/apps.js';", '')
    script = script.replace("const response=await fetch('/catalog.json');const apps=await response.json();",
                            'const apps=' + json.dumps(public_catalog()) + ';')
    base = re.sub(r'<script type="module">.*?</script>', '', html, flags=re.S)
    if args.output:
        args.output.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=args.chromium, headless=True,
                                    args=['--disable-dev-shm-usage'])
        page = browser.new_page(viewport={'width': 1380, 'height': 950}, device_scale_factor=1)
        page.set_default_timeout(10000)
        # Test assets are supplied in memory. No route may reach HA, Docker, or the internet.
        page.route('**/*', lambda route: route.abort())
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.set_content(base)
        page.add_script_tag(content=(ROOT / 'homeassistant/custom_components/opiha_apps/apps.js').read_text())
        page.evaluate('async()=>{' + script + '}')
        page.get_by_role('heading', name='ESPHome', exact=True).wait_for()
        if args.output:
            page.screenshot(path=str(args.output / 'PANEL-PREVIEW.png'), full_page=True)
        app = page.locator('article[data-id="esphome"]')
        app.get_by_role('button', name='Install', exact=True).click()
        page.get_by_role('button', name='Review plan').click()
        page.get_by_role('button', name='Approve install').click()
        app.get_by_role('button', name='Start', exact=True).wait_for()
        app.get_by_role('button', name='Start', exact=True).click()
        page.get_by_role('button', name='Approve start').click()
        app.get_by_role('button', name='Open', exact=True).wait_for()
        app.get_by_role('button', name='Open', exact=True).click()
        assert page.locator('iframe').get_attribute('src') == '/api/opiha_apps/ingress/esphome/'
        page.get_by_role('button', name='← Apps').click()
        page.get_by_role('button', name='Resource details').click()
        page.get_by_role('heading', name='Measured host and application resources').wait_for()
        page.get_by_role('button', name='Close', exact=True).click()
        page.set_viewport_size({'width': 390, 'height': 844})
        if args.output:
            page.screenshot(path=str(args.output / 'PANEL-MOBILE-PREVIEW.png'), full_page=True)
        if errors:
            raise AssertionError(errors)
        browser.close()
    print(json.dumps({'result': 'passed', 'checks': ['install approval', 'start approval', 'frame route', 'metrics dialog', 'mobile rendering'],
                      'data': 'synthetic', 'actual_HA': False, 'actual_Docker': False, 'browser_network': False}, indent=2))

if __name__ == '__main__':
    main()

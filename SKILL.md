---
name: acs-journal-downloader
description: Download papers from ACS journals through institutional library access with browser automation, Shibboleth SSO, and PDF blob extraction. Use when downloading ACS journal issues such as Journal of Medicinal Chemistry, especially when access requires library login, multi-step gateway pages, SSO consent screens, dynamic PDF links, or issue-specific URLs by journal/volume/issue.
---

# ACS Journal Downloader

Use this skill to download ACS journal issue PDFs through a library gateway.

## Workflow

1. Log in to the library portal with configured credentials.
2. Open the configured ACS entry page from the library.
3. Complete the gateway flow:
   - Click `第一步点我` if present.
   - Return to the ACS entry page.
   - Click `第二步点我`.
4. Complete Shibboleth / SSO consent:
   - If a consent page appears, select the remember-consent option when available.
   - Click the accept / proceed button.
5. Open the ACS TOC page:
   - Latest issue: `https://pubs.acs.org/toc/<journal>/current`
   - Specific issue: `https://pubs.acs.org/toc/<journal>/<volume>/<issue>`
6. Collect all `a[href*="/doi/pdf/"]` links from the issue page.
7. For each PDF link:
   - Open the PDF page.
   - Confirm `document.contentType === "application/pdf"`.
   - Use in-page `fetch()` + `blob()` + `FileReader.readAsDataURL()` to extract bytes.
   - Decode base64 in Python and save the real PDF.

## Important implementation detail

Do **not** rely on browser print-to-PDF (`page.pdf()`) for article downloads. That only saves a rendered page snapshot and can produce fake small PDFs. The correct method is to fetch the PDF blob from the ACS PDF page and save the blob bytes.

## Issue selection

Support both modes:

- Latest issue: no volume/issue arguments
- Specific issue: pass both `--volume` and `--issue`

Examples:

```bash
python acs_downloader.py jmcmar
python acs_downloader.py jmcmar --volume 69 --issue 6
```

## Handling friction pages

If automation encounters protection or access friction, use these strategies in order.

### 1. Library login page / simple verification

- Prefer normal form filling first.
- Reuse browser profile to preserve cookies and reduce repeated checks.
- Keep headed mode enabled when the site behaves differently in headless mode.

### 2. Shibboleth / institutional consent page

- Look for remember-consent radio/button values such as `_shib_idp_rememberConsent`.
- Click proceed/accept controls such as `_eventId_proceed`.
- Wait after clicking; some ACS flows redirect through `saml2post` pages before landing on ACS.

### 3. Cloudflare / Turnstile / challenge pages

If a page shows Cloudflare verification, Turnstile, or anti-bot interstitials:

- Run in headed mode first.
- Reuse a persistent browser profile.
- Prefer real Chromium/Chrome automation with stable cookies.
- If standard browser automation fails, use the existing Cloudflare bypass path in the workspace:
  - Scrapling / real Chrome
  - `solve_cloudflare=True`
  - non-headless mode
  - Xvfb display when needed on servers
- If this still fails, consult `references/troubleshooting.md` and the existing Turnstile-Solver notes in the workspace.

### 4. PDF page loads but download is wrong

Symptoms:
- tiny PDF (< 100 KB)
- one-page "snapshot" PDF
- HTML saved instead of PDF

Fix:
- verify `document.contentType` is `application/pdf`
- do not use raw curl-only download as the primary method unless cookies and referer are proven sufficient
- do not use `page.pdf()` for the article itself
- use `fetch(window.location.href)` inside the authenticated browser page, then save blob bytes

## When to read more

- Read `references/troubleshooting.md` when login flow changes, SSO pages differ, Cloudflare appears, or saved files are too small.

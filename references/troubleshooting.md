# Troubleshooting

## 1. Login succeeds but ACS is not reached

Check:
- ACS entry URL is still valid
- `第一步点我` / `第二步点我` buttons still exist
- a new popup page is not left open and blocking navigation
- SSO consent page still uses the same control names

Recovery:
- close extra tabs
- revisit the ACS entry page
- repeat first-step then second-step flow
- wait longer after SSO accept

## 2. SSO page changed

Known successful selectors:
- remember consent: `input[value="_shib_idp_rememberConsent"]`
- proceed button: `input[name="_eventId_proceed"]`

If they change:
- inspect all inputs/buttons on the page
- search for accept/proceed/consent/remember text
- save screenshot + HTML for diffing

## 3. Cloudflare / Turnstile / anti-bot challenge

Recommended sequence:
1. Retry in headed mode
2. Reuse persistent profile directory
3. Slow down actions and preserve cookies
4. Use Scrapling with real Chrome and challenge solving if needed
5. Keep non-headless and use Xvfb on headless servers

Known-good pattern from this workspace:
- real Chrome
- `solve_cloudflare=True`
- non-headless
- persistent user data dir
- Xvfb display (`DISPLAY=:99` or `xvfb-run -a`)

## 4. PDF links are found but downloaded files are fake

Bad signs:
- 1 page only
- a few hundred KB when article should be several MB
- output title looks correct but content is just rendered webpage

Cause:
- using Playwright/Patchright `page.pdf()` on the browser page

Fix:
- open the ACS PDF URL inside the authenticated browser context
- confirm `document.contentType == "application/pdf"`
- run `fetch(window.location.href)` inside the page
- read response as blob
- convert blob to base64 in page JS
- decode and save in Python

## 5. Curl download returns HTML instead of PDF

Cause:
- missing browser session state, referer, or JS-mediated auth state

Fix:
- prefer in-browser authenticated fetch instead of curl
- only use curl after proving that cookies + headers are enough

## 6. Specific issue download fails

Expected URL shape:
- latest: `https://pubs.acs.org/toc/<journal>/current`
- specific issue: `https://pubs.acs.org/toc/<journal>/<volume>/<issue>`

Example:
- `https://pubs.acs.org/toc/jmcmar/69/6`

Check:
- correct journal code
- volume and issue both set
- target issue exists

## 7. Recommended debug artifacts

When something breaks, save:
- current URL
- screenshot PNG
- page HTML
- visible text excerpt
- all buttons/inputs on the current page
- PDF blob size if PDF page is reached

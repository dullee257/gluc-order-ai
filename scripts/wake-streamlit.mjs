/**
 * Streamlit Community Cloud 앱이 잠들었을 때 "Yes, get this app back up!" 버튼을
 * 자동으로 눌러 앱을 깨웁니다. GitHub Actions 등에서 주기 실행용.
 *
 * 사용: STREAMLIT_APP_URL 또는 APP_URL 환경 변수 (없으면 nutrisort.streamlit.app)
 *   node scripts/wake-streamlit.mjs
 */
import { chromium } from 'playwright';

const APP_URL = (process.env.STREAMLIT_APP_URL || process.env.APP_URL || 'https://nutrisort.streamlit.app').trim();

async function main() {
  let browser;
  try {
    browser = await chromium.launch({ headless: true });
    const page = await browser.newPage();

    await page.goto(APP_URL, { waitUntil: 'domcontentloaded', timeout: 30000 });
    await page.waitForTimeout(5000);

    // Streamlit 슬립 페이지: 버튼 또는 링크로 "Yes, get this app back up!" 표시
    const selectors = [
      page.getByRole('button', { name: /yes, get this app back up/i }),
      page.locator('a:has-text("Yes, get this app back up!")'),
      page.locator('text=Yes, get this app back up!').first(),
    ];
    let clicked = false;
    for (const sel of selectors) {
      const el = sel.first();
      if (await el.isVisible().catch(() => false)) {
        await el.click();
        clicked = true;
        break;
      }
    }
    if (clicked) {
      await page.waitForTimeout(15000);
    }

    await browser.close();
  } catch (err) {
    console.error('Wake script error:', err.message);
    if (browser) await browser.close();
    process.exit(1);
  }
}

main();

// Passive Canva AI-layer executor for a browser-client Tab.
// The caller owns browser selection, tab creation, start/end pages, and user reporting.

function normalizeText(value) {
  return String(value || "").replace(/\s+/g, " ").trim();
}

function centerOf(rect) {
  if (!rect) throw new Error("Missing rect");
  return {
    x: Math.round(rect.x + rect.w / 2),
    y: Math.round(rect.y + rect.h / 2),
  };
}

function blockerText(items) {
  return items.map((item) => item.text || item.aria).filter(Boolean).join(" | ");
}

export function installCanvaAiLayerRunner(tab, options = {}) {
  const wait = {
    afterNavigationMs: options.afterNavigationMs ?? 1800,
    afterSelectMs: options.afterSelectMs ?? 800,
    afterPanelMs: options.afterPanelMs ?? 1000,
    afterAiClickMs: options.afterAiClickMs ?? 2000,
  };

  async function clickRect(rect) {
    const point = centerOf(rect);
    await tab.cua.click(point);
  }

  async function state() {
    return await tab.playwright.evaluate(() => {
      const textOf = (el) => (el?.innerText || el?.textContent || "").replace(/\s+/g, " ").trim();
      const visibleItems = [...document.querySelectorAll("button,p,span,h5,input,div[aria-label]")]
        .map((el, i) => {
          const r = el.getBoundingClientRect();
          return {
            i,
            tag: el.tagName,
            text: textOf(el),
            aria: el.getAttribute("aria-label"),
            placeholder: el.getAttribute("placeholder"),
            value: el.value || null,
            rect: {
              x: Math.round(r.x),
              y: Math.round(r.y),
              w: Math.round(r.width),
              h: Math.round(r.height),
            },
            visible:
              r.width > 0 &&
              r.height > 0 &&
              r.x > -30 &&
              r.y > -30 &&
              r.x < innerWidth + 30 &&
              r.y < innerHeight + 30,
          };
        })
        .filter((item) => item.visible);

      const pageText =
        [...document.querySelectorAll("span.khPe7Q")]
          .map((el) => textOf(el))
          .find((text) => /^\d+\s*\/\s*\d+$/.test(text)) || null;
      const pageInput = visibleItems.find(
        (item) => item.tag === "INPUT" && item.aria === "转至页面",
      ) || null;
      const totalText = visibleItems.find((item) => /^\/\s*\d+$/.test(item.text || ""))?.text || null;
      const computedPage =
        pageText ||
        (pageInput && totalText
          ? `${pageInput.value || pageInput.placeholder}${totalText.replace(/\s+/g, "")}`
          : null);

      const blocker = visibleItems
        .filter((item) => {
          const text = [item.text, item.aria].filter(Boolean).join(" ");
          const modalish = item.rect.x > 230 && item.rect.y > 40 && item.rect.w > 180;
          return (
            modalish &&
            /升级获取更多AI使用次数|Canva可画高级版|免费试用\s*7|试用期结束|高级版的所有功能|错误|失败|无法/.test(
              text,
            )
          );
        })
        .slice(0, 8);

      const save =
        visibleItems.find((item) => /保存|更改/.test(item.aria || item.text || "")) || null;
      const editPanel =
        visibleItems.find((item) => item.tag === "H5" && item.text === "编辑图片") || null;
      const aiLayer =
        visibleItems.find(
          (item) => item.tag === "BUTTON" && (item.aria === "AI图层" || item.text === "AI图层"),
        ) || null;
      const toolbarEdit =
        visibleItems
          .filter(
            (item) =>
              item.tag === "BUTTON" &&
              item.text === "编辑" &&
              item.rect.y > 50 &&
              item.rect.y < 130 &&
              item.rect.w <= 110,
          )
          .sort((a, b) => a.rect.x - b.rect.x)[0] || null;

      return {
        computedPage,
        pageText,
        pageInput,
        totalText,
        save,
        blocker,
        editPanel,
        aiLayer,
        toolbarEdit,
        title: document.title,
        href: location.href,
      };
    });
  }

  async function pageButtonRect() {
    return await tab.playwright.evaluate(() => {
      const textOf = (el) => (el?.innerText || el?.textContent || "").replace(/\s+/g, " ").trim();
      const buttons = [...document.querySelectorAll("button")]
        .map((el) => {
          const r = el.getBoundingClientRect();
          return {
            text: textOf(el),
            rect: {
              x: Math.round(r.x),
              y: Math.round(r.y),
              w: Math.round(r.width),
              h: Math.round(r.height),
            },
          };
        })
        .filter((item) => /^\d+\s*\/\s*\d+$/.test(item.text) && item.rect.w > 20 && item.rect.h > 15)
        .sort((a, b) => b.rect.y - a.rect.y);
      return buttons[0]?.rect || null;
    });
  }

  async function navigateToPage(page) {
    let input = tab.playwright.locator('input[aria-label="转至页面"]');
    let count = await input.count();

    if (count !== 1) {
      const rect = await pageButtonRect();
      if (!rect) throw new Error("Page button not found");
      await clickRect(rect);
      await tab.playwright.waitForTimeout(300);
      input = tab.playwright.locator('input[aria-label="转至页面"]');
      count = await input.count();
    }

    if (count !== 1) throw new Error(`Page input count ${count}`);
    await input.fill(String(page), { timeoutMs: 8000 });
    await input.press("Enter", { timeoutMs: 8000 });
    await tab.playwright.waitForTimeout(wait.afterNavigationMs);

    let current = await state();
    if (!current.computedPage || !current.computedPage.startsWith(`${page}/`)) {
      await tab.playwright.waitForTimeout(1200);
      current = await state();
    }
    if (!current.computedPage || !current.computedPage.startsWith(`${page}/`)) {
      throw new Error(`Navigation to page ${page} not confirmed; current=${current.computedPage}`);
    }
    return current.computedPage;
  }

  async function mainImageRect() {
    return await tab.playwright.evaluate(() => {
      const images = [...document.querySelectorAll("img")]
        .map((el) => {
          const r = el.getBoundingClientRect();
          return {
            rect: {
              x: Math.round(r.x),
              y: Math.round(r.y),
              w: Math.round(r.width),
              h: Math.round(r.height),
            },
            area: Math.round(r.width * r.height),
          };
        })
        .filter(
          (item) =>
            item.rect.w > 300 &&
            item.rect.h > 180 &&
            item.rect.x >= 60 &&
            item.rect.y >= 60 &&
            item.rect.x < innerWidth &&
            item.rect.y < innerHeight,
        )
        .sort((a, b) => b.area - a.area);
      return images[0]?.rect || null;
    });
  }

  function assertNoBlocker(page, current, phase) {
    if (!current.blocker?.length) return;
    const error = new Error(`Page ${page} blocked ${phase}: ${blockerText(current.blocker)}`);
    error.page = page;
    error.phase = phase;
    error.blockers = current.blocker;
    throw error;
  }

  async function processPage(page) {
    const nav = await navigateToPage(page);
    let current = await state();
    assertNoBlocker(page, current, "before action");

    const imageRect = await mainImageRect();
    if (!imageRect) throw new Error(`Page ${page}: main image not found`);

    await clickRect(imageRect);
    await tab.playwright.waitForTimeout(wait.afterSelectMs);
    current = await state();

    if (!current.toolbarEdit) {
      await clickRect(imageRect);
      await tab.playwright.waitForTimeout(wait.afterSelectMs);
      current = await state();
    }
    if (!current.toolbarEdit) throw new Error(`Page ${page}: toolbar edit not found`);

    await clickRect(current.toolbarEdit.rect);
    await tab.playwright.waitForTimeout(wait.afterPanelMs);
    current = await state();
    assertNoBlocker(page, current, "opening edit panel");

    if (!current.editPanel) throw new Error(`Page ${page}: edit image panel not open`);
    if (!current.aiLayer) {
      return {
        page,
        status: "already_converted_or_ai_layer_missing",
        nav,
        pageAfter: current.computedPage,
        save: current.save?.aria || current.save?.text || null,
      };
    }

    const aiLayer = tab.playwright.locator('button[aria-label="AI图层"]');
    const count = await aiLayer.count();
    if (count !== 1) throw new Error(`Page ${page}: AI layer button count ${count}`);
    await aiLayer.click({ timeoutMs: 10000 });
    await tab.playwright.waitForTimeout(wait.afterAiClickMs);

    current = await state();
    assertNoBlocker(page, current, "after AI layer click");
    return {
      page,
      status: "ai_layer_clicked",
      nav,
      pageAfter: current.computedPage,
      save: current.save?.aria || current.save?.text || null,
    };
  }

  async function processRange(startPage, endPage, rangeOptions = {}) {
    const results = [];
    for (let page = startPage; page <= endPage; page += 1) {
      const result = await processPage(page);
      results.push(result);
      if (typeof rangeOptions.onProgress === "function") {
        await rangeOptions.onProgress(result);
      }
    }
    return {
      startPage,
      endPage,
      count: results.length,
      results,
      finalState: await state(),
    };
  }

  return {
    clickRect,
    mainImageRect,
    navigateToPage,
    pageButtonRect,
    processPage,
    processRange,
    state,
    text: normalizeText,
  };
}

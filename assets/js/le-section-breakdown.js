/* Shared LE closing-cost section itemization — le-upload.js + le-compare.js */
(function (global) {
  const SECTION_ITEM_KEYS = ['a', 'b', 'c', 'e', 'f', 'g', 'h'];

  const SECTION_ITEM_CONFIG = [
    ['a', 'A · Origination', 'section_a'],
    ['b', 'B · Cannot shop', 'section_b'],
    ['c', 'C · Can shop', 'section_c'],
    ['e', 'E · Govt fees', 'section_e'],
    ['f', 'F · Prepaids', 'section_f'],
    ['g', 'G · Escrow', 'section_g'],
    ['h', 'H · Other', 'section_h']
  ];

  function parseMoneyInput(val) {
    return Number(String(val || '').replace(/[,$]/g, '')) || 0;
  }

  function sumSectionItems(sectionItems, key) {
    return (sectionItems[key] || []).reduce((s, i) => s + (Number(i.amount) || 0), 0);
  }

  function normalizeClientSectionItems(fields) {
    const out = {};
    const src = fields.section_items && typeof fields.section_items === 'object' ? fields.section_items : {};
    SECTION_ITEM_KEYS.forEach((k) => {
      out[k] = (Array.isArray(src[k]) ? src[k] : [])
        .map((item) => ({
          name: String(item?.name || '').trim(),
          amount: Math.round(parseMoneyInput(item?.amount))
        }))
        .filter((item) => item.name && item.amount > 0);
    });
    const legacy = Array.isArray(fields.shop_items) ? fields.shop_items : [];
    if (legacy.length && !out.c.length) {
      out.c = legacy
        .map((item) => ({
          name: String(item?.name || '').trim(),
          amount: Math.round(parseMoneyInput(item?.amount))
        }))
        .filter((item) => item.name && item.amount > 0);
    }
    return out;
  }

  function lineItemName(inp) {
    return inp.dataset.lineName
      || inp.closest('.le-line-item')?.querySelector('[data-line-label]')?.value?.trim()
      || inp.closest('.le-line-item')?.querySelector('span')?.textContent?.trim()
      || 'Item';
  }

  function getSectionItemsFromDom($, prefix) {
    const root = $(prefix + '_sections_detail');
    const out = {};
    if (!root) return out;
    SECTION_ITEM_KEYS.forEach((k) => {
      const grid = root.querySelector(`[data-section-items="${k}"]`);
      if (!grid) {
        out[k] = [];
        return;
      }
      out[k] = Array.from(grid.querySelectorAll('[data-line-amount]')).map((inp) => ({
        name: lineItemName(inp),
        amount: Math.round(parseMoneyInput(inp.value))
      })).filter((item) => item.name && item.amount > 0);
    });
    return out;
  }

  function resolvePointsFromFields(fields) {
    const amount = Number(fields.amount) || 0;
    let pointsDollars = Number(fields.points_dollars) || 0;
    let pointsPct = Number(fields.points_pct) || 0;
    if (!pointsDollars && pointsPct > 0 && amount > 0) {
      pointsDollars = (amount * pointsPct) / 100;
    }
    if (!pointsPct && pointsDollars > 0 && amount > 0) {
      pointsPct = Math.round((pointsDollars / amount) * 100000) / 1000;
    }
    if (!pointsDollars && Number(fields.points) > 0 && amount > 0) {
      const pts = Number(fields.points);
      if (pts <= 5) {
        pointsPct = pts;
        pointsDollars = (amount * pts) / 100;
      } else {
        pointsDollars = pts;
        pointsPct = Math.round((pts / amount) * 100000) / 1000;
      }
    }
    return {
      pointsDollars: pointsDollars > 0 ? Math.round(pointsDollars) : 0,
      pointsPct: pointsPct > 0 ? pointsPct : 0
    };
  }

  function prepareSectionFields(fields) {
    const sectionA = Number(fields.section_a) || 0;
    const { pointsDollars, pointsPct } = resolvePointsFromFields(fields);
    const sectionItems = normalizeClientSectionItems(fields);

    const sectionASum = sumSectionItems(sectionItems, 'a');
    const shopSum = sumSectionItems(sectionItems, 'c');
    const other3pSum = sumSectionItems(sectionItems, 'b') + sumSectionItems(sectionItems, 'e') + sumSectionItems(sectionItems, 'h');
    const prepaidsSum = sumSectionItems(sectionItems, 'f') + sumSectionItems(sectionItems, 'g');

    let lenderFees = Number(fields.lender_fees) || sectionA;
    const aBase = sectionASum > 0 ? sectionASum : sectionA;
    if (aBase > 0 && pointsDollars > 0 && aBase >= pointsDollars) {
      lenderFees = aBase - pointsDollars;
    }

    return {
      ...fields,
      points: pointsDollars > 0 ? pointsDollars : (fields.points || ''),
      points_pct: pointsPct > 0 ? pointsPct : (fields.points_pct || ''),
      points_dollars: pointsDollars,
      lender_fees: lenderFees > 0 ? Math.round(lenderFees) : fields.lender_fees,
      shop_total: shopSum > 0 ? Math.round(shopSum) : fields.shop_total,
      other_3p: other3pSum > 0 ? Math.round(other3pSum) : fields.other_3p,
      prepaids: prepaidsSum > 0 ? Math.round(prepaidsSum) : fields.prepaids,
      section_items: sectionItems
    };
  }

  function renderLineItemRow(item, idx, sectionKey) {
    const label = String(item.name || 'Item').replace(/</g, '&lt;');
    const amt = Math.round(Number(item.amount) || 0);
    return `<label class="le-line-item"><span>${label}</span><input type="text" inputmode="decimal" data-line-amount data-line-name="${label}" data-section="${sectionKey}" data-line-idx="${idx}" value="${amt}"></label>`;
  }

  function createApi($, hooks) {
    const { onRollupChange } = hooks || {};

    function syncSectionRollups(prefix) {
      const sectionItems = getSectionItemsFromDom($, prefix);
      const pointsDollars = parseMoneyInput($(prefix + '_points')?.value);
      const sectionASum = sumSectionItems(sectionItems, 'a');
      const shopSum = sumSectionItems(sectionItems, 'c');
      const other3pSum = sumSectionItems(sectionItems, 'b') + sumSectionItems(sectionItems, 'e') + sumSectionItems(sectionItems, 'h');
      const prepaidsSum = sumSectionItems(sectionItems, 'f') + sumSectionItems(sectionItems, 'g');

      const shopEl = $(prefix + '_shop_total');
      const otherEl = $(prefix + '_other_3p');
      const prepaidsEl = $(prefix + '_prepaids');
      const lenderEl = $(prefix + '_lender_fees');

      if (shopSum > 0 && shopEl) shopEl.value = Math.round(shopSum);
      if (other3pSum > 0 && otherEl) otherEl.value = Math.round(other3pSum);
      if (prepaidsSum > 0 && prepaidsEl) prepaidsEl.value = Math.round(prepaidsSum);
      if (sectionASum > 0 && lenderEl) {
        lenderEl.value = Math.round(Math.max(0, sectionASum - pointsDollars));
      }

      const root = $(prefix + '_sections_detail');
      if (root) {
        SECTION_ITEM_CONFIG.forEach(([key]) => {
          const sum = sumSectionItems(sectionItems, key);
          const sumEl = root.querySelector(`[data-section-sum="${key}"]`);
          if (sumEl) sumEl.textContent = sum > 0 ? '$' + sum.toLocaleString() : '';
        });
      }
      onRollupChange?.(prefix);
    }

    function syncPointsFields(prefix, source) {
      const amount = parseMoneyInput($(prefix + '_amount')?.value);
      const dollarsEl = $(prefix + '_points');
      const pctEl = $(prefix + '_points_pct');
      if (!dollarsEl || !pctEl || amount <= 0) return;

      if (source === 'dollars') {
        const dollars = parseMoneyInput(dollarsEl.value);
        if (dollars > 0) {
          pctEl.value = String(Math.round((dollars / amount) * 100000) / 1000);
        } else if (!dollarsEl.value) {
          pctEl.value = '';
        }
      } else if (source === 'pct') {
        const pct = parseMoneyInput(pctEl.value);
        if (pct > 0) {
          dollarsEl.value = String(Math.round((amount * pct) / 100));
        } else if (!pctEl.value) {
          dollarsEl.value = '';
        }
      }
      syncSectionRollups(prefix);
    }

    function wireLineItemInputs(root, prefix) {
      root.querySelectorAll('input[data-line-amount]').forEach((inp) => {
        inp.addEventListener('input', () => syncSectionRollups(prefix));
      });
      root.querySelectorAll('[data-line-label]').forEach((inp) => {
        inp.addEventListener('input', () => {
          const amountInp = inp.closest('.le-line-item')?.querySelector('[data-line-amount]');
          if (amountInp) amountInp.dataset.lineName = inp.value.trim();
        });
      });
    }

    function addManualLine(prefix, sectionKey) {
      const grid = $(prefix + '_sections_detail')?.querySelector(`[data-section-items="${sectionKey}"]`);
      if (!grid) return;
      const idx = grid.querySelectorAll('[data-line-amount]').length;
      const row = document.createElement('label');
      row.className = 'le-line-item le-line-item--manual';
      row.innerHTML = `<span><input type="text" class="le-line-name" placeholder="Item name" data-line-label></span><input type="text" inputmode="decimal" data-line-amount data-section="${sectionKey}" data-line-idx="${idx}" placeholder="0">`;
      grid.appendChild(row);
      wireLineItemInputs(grid, prefix);
    }

    function renderSectionBreakdown(prefix, sectionItems, prepared) {
      const wrap = $(prefix + '_sections_wrap');
      const root = $(prefix + '_sections_detail');
      if (!wrap || !root) return;

      const blocks = SECTION_ITEM_CONFIG.map(([key, label, totalKey]) => {
        const items = sectionItems[key] || [];
        const sectionTotal = Number(prepared[totalKey]) || 0;
        if (!items.length && sectionTotal <= 0) return '';
        const rows = items.length
          ? items.map((item, idx) => renderLineItemRow(item, idx, key)).join('')
          : `<p class="le-section-empty tiny">No line items — section total $${sectionTotal.toLocaleString()}</p>`;
        const sum = items.length ? sumSectionItems(sectionItems, key) : sectionTotal;
        const sumLabel = sum > 0 ? '$' + sum.toLocaleString() : '';
        return `<details class="le-section-nested" data-section-block="${key}"><summary>${label}<span class="le-section-sum" data-section-sum="${key}">${sumLabel}</span></summary><div class="le-line-items-grid" data-section-items="${key}">${rows}</div><button type="button" class="le-add-line tiny" data-add-section="${key}" data-prefix="${prefix}">+ Add line item</button></details>`;
      }).filter(Boolean);

      if (!blocks.length) {
        root.innerHTML = '';
        wrap.hidden = true;
        return;
      }

      root.innerHTML = blocks.join('');
      wrap.hidden = false;
      wireLineItemInputs(root, prefix);
      root.querySelectorAll('[data-add-section]').forEach((btn) => {
        btn.addEventListener('click', () => addManualLine(btn.dataset.prefix, btn.dataset.addSection));
      });
    }

    function initManualSections(prefix) {
      const wrap = $(prefix + '_sections_wrap');
      const root = $(prefix + '_sections_detail');
      if (!wrap || !root || root.children.length) return;

      root.innerHTML = SECTION_ITEM_CONFIG.map(([key, label]) =>
        `<details class="le-section-nested"><summary>${label}<span class="le-section-sum" data-section-sum="${key}"></span></summary><div class="le-line-items-grid" data-section-items="${key}"></div><button type="button" class="le-add-line tiny" data-add-section="${key}" data-prefix="${prefix}">+ Add line item</button></details>`
      ).join('');
      wrap.hidden = false;
      root.querySelectorAll('[data-add-section]').forEach((btn) => {
        btn.addEventListener('click', () => addManualLine(btn.dataset.prefix, btn.dataset.addSection));
      });
    }

    function clearSectionBreakdown(prefix) {
      const detail = $(prefix + '_sections_detail');
      if (detail) detail.innerHTML = '';
      const wrap = $(prefix + '_sections_wrap');
      if (wrap) wrap.hidden = true;
    }

    function handleFormInput(prefix, target) {
      if (target?.id === prefix + '_points') syncPointsFields(prefix, 'dollars');
      else if (target?.id === prefix + '_points_pct') syncPointsFields(prefix, 'pct');
      else if (target?.id === prefix + '_amount') {
        if ($(prefix + '_points')?.value) syncPointsFields(prefix, 'dollars');
        else if ($(prefix + '_points_pct')?.value) syncPointsFields(prefix, 'pct');
        else syncSectionRollups(prefix);
      } else syncSectionRollups(prefix);
    }

    return {
      syncSectionRollups,
      syncPointsFields,
      renderSectionBreakdown,
      initManualSections,
      clearSectionBreakdown,
      handleFormInput,
      addManualLine
    };
  }

  global.LESectionBreakdown = {
    SECTION_ITEM_KEYS,
    SECTION_ITEM_CONFIG,
    parseMoneyInput,
    sumSectionItems,
    normalizeClientSectionItems,
    getSectionItemsFromDom,
    resolvePointsFromFields,
    prepareSectionFields,
    createApi
  };
})(typeof window !== 'undefined' ? window : global);

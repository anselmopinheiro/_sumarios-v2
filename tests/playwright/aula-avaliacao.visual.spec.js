const { test, expect } = require('playwright/test');

const targetPath = process.env.AULA_AVALIACAO_PATH || '/aula/48/avaliacao';
const postPathFragment = '/avaliacao/obser';

async function waitForAvaliacaoFrame(page) {
  await expect(page.locator('#avaliacao-frame')).toBeVisible();
  await expect
    .poll(() => {
      const frame = page.frames().find((item) => item.url().includes(postPathFragment));
      return frame ? frame.url() : '';
    })
    .not.toBe('');
  return page.frames().find((item) => item.url().includes(postPathFragment));
}

async function openAvaliacao(page) {
  await page.goto(targetPath, { waitUntil: 'domcontentloaded' });

  await expect(page.getByRole('heading', { name: /Avalia/i })).toBeVisible();
  await expect(page.locator('#avaliacao-tabs')).toBeVisible();
  await expect(page.locator('#save-indicator')).toBeVisible();
  await expect(page.locator('#avaliacao-frame')).toBeVisible();

  const frame = await waitForAvaliacaoFrame(page);
  const frameLocator = page.frameLocator('#avaliacao-frame');
  const grid = frameLocator.locator('#avaliacao-objeto-table, #avaliacao-table').first();

  await expect(grid).toBeVisible({ timeout: 30_000 });
  await expect(frameLocator.locator('#avaliacao-save-button')).toBeVisible();
  await expect(frameLocator.locator('thead').first()).toBeVisible();
  await expect(frameLocator.locator('tbody tr').first()).toBeVisible();

  return { frame, frameLocator, grid };
}

function attachPostCounter(page) {
  let postCount = 0;
  page.on('request', (request) => {
    if (request.method() === 'POST' && request.url().includes(postPathFragment)) {
      postCount += 1;
    }
  });
  return {
    get count() {
      return postCount;
    },
  };
}

function attachConsoleErrorTracker(page) {
  const messages = [];
  page.on('console', (message) => {
    if (message.type() === 'error') {
      messages.push(message.text());
    }
  });
  page.on('pageerror', (error) => {
    messages.push(error.message || String(error));
  });
  return {
    get messages() {
      return [...messages];
    },
  };
}

function studentRubricSelector(alunoId, rubricaId) {
  return `.js-student-score[data-aluno-id="${alunoId}"][data-rubrica-id="${rubricaId}"]`;
}

function componentSelector(alunoId, rubricaId, componentId) {
  return `.js-component-score[data-aluno-id="${alunoId}"][data-rubrica-id="${rubricaId}"][data-component-id="${componentId}"]`;
}

function numericValuePattern(expectedValue) {
  const numericValue = Number(expectedValue);
  const normalizedValue = Number.isFinite(numericValue) ? String(numericValue) : String(expectedValue);
  const escapedValue = normalizedValue.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  if (escapedValue.includes('\\.')) {
    return new RegExp(`^${escapedValue}0*$`);
  }
  return new RegExp(`^${escapedValue}(?:\\.0+)?$`);
}

async function resolveCopyScenario(frame, studentCount) {
  return frame.evaluate(({ studentCount }) => {
    const payload = JSON.parse(document.getElementById('avaliacao-domain-copy-config')?.textContent || '[]');
    const allRows = Array.from(document.querySelectorAll('tr[data-aluno-id][data-presente="1"]'));
    const preferredRows = allRows.filter((row) => !(row.dataset.groupId || ''));
    const candidateRows = preferredRows.length >= studentCount ? preferredRows : allRows;
    if (candidateRows.length < studentCount) return null;

    const normalizeKey = (rawValue) =>
      String(rawValue || '')
        .normalize('NFD')
        .replace(/[\u0300-\u036f]/g, '')
        .trim()
        .toLowerCase()
        .replace(/\s+/g, ' ');

    const uniqueMap = (items, resolver) => {
      const counts = new Map();
      (items || []).forEach((item) => {
        const key = resolver(item);
        if (!key) return;
        counts.set(key, (counts.get(key) || 0) + 1);
      });
      const map = new Map();
      (items || []).forEach((item) => {
        const key = resolver(item);
        if (!key || counts.get(key) !== 1) return;
        map.set(key, item);
      });
      return map;
    };

    const rubricKey = (rubric) => {
      const code = normalizeKey(rubric?.codigo);
      if (code) return `code:${code}`;
      const name = normalizeKey(rubric?.nome);
      return name ? `name:${name}` : '';
    };

    const componentKey = (component) => {
      const code = normalizeKey(component?.codigo);
      if (code) return `code:${code}`;
      const name = normalizeKey(component?.nome);
      return name ? `name:${name}` : '';
    };

    const buildPlan = (sourceDomain, targetDomain) => {
      const sourceRubrics = Array.isArray(sourceDomain?.rubricas) ? sourceDomain.rubricas : [];
      const targetRubrics = Array.isArray(targetDomain?.rubricas) ? targetDomain.rubricas : [];
      const sourceMap = uniqueMap(sourceRubrics, rubricKey);
      const targetMap = uniqueMap(targetRubrics, rubricKey);
      const mappings = [];
      let skippedDueToComponentMismatch = 0;
      sourceMap.forEach((sourceRubric, key) => {
        const targetRubric = targetMap.get(key);
        if (!targetRubric) return;
        const sourceComponents = Array.isArray(sourceRubric.components) ? sourceRubric.components : [];
        const targetComponents = Array.isArray(targetRubric.components) ? targetRubric.components : [];
        if (!sourceComponents.length && !targetComponents.length) {
          mappings.push({
            sourceRubricId: String(sourceRubric.id),
            targetRubricId: String(targetRubric.id),
            componentMappings: [],
          });
          return;
        }
        if (!sourceComponents.length || !targetComponents.length) {
          skippedDueToComponentMismatch += 1;
          return;
        }
        const sourceComponentMap = uniqueMap(sourceComponents, componentKey);
        const targetComponentMap = uniqueMap(targetComponents, componentKey);
        const componentMappings = [];
        sourceComponentMap.forEach((sourceComponent, componentMatchKey) => {
          const targetComponent = targetComponentMap.get(componentMatchKey);
          if (!targetComponent) return;
          componentMappings.push({
            sourceId: String(sourceComponent.id),
            targetId: String(targetComponent.id),
          });
        });
        if (componentMappings.length !== sourceComponents.length || componentMappings.length !== targetComponents.length) {
          skippedDueToComponentMismatch += 1;
          return;
        }
        mappings.push({
          sourceRubricId: String(sourceRubric.id),
          targetRubricId: String(targetRubric.id),
          componentMappings,
        });
      });
      return {
        mappings,
        skippedDueToComponentMismatch,
      };
    };

    for (const sourceDomain of payload) {
      for (const targetDomain of payload) {
        if (!sourceDomain?.client_id || !targetDomain?.client_id || sourceDomain.client_id === targetDomain.client_id) continue;
        const plan = buildPlan(sourceDomain, targetDomain);
        const mapping = plan.mappings.find((candidate) => {
          const firstAlunoId = candidateRows[0]?.dataset.alunoId;
          if (!firstAlunoId) return false;
          if (candidate.componentMappings.length) {
            return candidate.componentMappings.every(({ sourceId, targetId }) => (
              document.querySelector(`.js-component-score[data-aluno-id="${firstAlunoId}"][data-rubrica-id="${candidate.sourceRubricId}"][data-component-id="${sourceId}"]`) &&
              document.querySelector(`.js-component-score[data-aluno-id="${firstAlunoId}"][data-rubrica-id="${candidate.targetRubricId}"][data-component-id="${targetId}"]`)
            ));
          }
          const sourceInput = document.querySelector(`.js-student-score[data-aluno-id="${firstAlunoId}"][data-rubrica-id="${candidate.sourceRubricId}"]`);
          const targetInput = document.querySelector(`.js-student-score[data-aluno-id="${firstAlunoId}"][data-rubrica-id="${candidate.targetRubricId}"]`);
          return sourceInput && targetInput && !sourceInput.readOnly && !targetInput.readOnly;
        });
        if (!mapping) continue;
        return {
          sourceDomainId: sourceDomain.client_id,
          targetDomainId: targetDomain.client_id,
          mapping,
          skippedDueToComponentMismatch: plan.skippedDueToComponentMismatch,
          studentIds: candidateRows.slice(0, studentCount).map((row) => String(row.dataset.alunoId)),
        };
      }
    }
    return null;
  }, { studentCount });
}

async function resolveGroupedOverrideCopyScenario(frame) {
  return frame.evaluate(() => {
    const payload = JSON.parse(document.getElementById('avaliacao-domain-copy-config')?.textContent || '[]');
    const groupedRows = Array.from(document.querySelectorAll('tr[data-aluno-id][data-presente="1"]'))
      .filter((row) => Boolean(row.dataset.groupId || ''));
    if (groupedRows.length < 2) return null;

    const normalizeKey = (rawValue) =>
      String(rawValue || '')
        .normalize('NFD')
        .replace(/[\u0300-\u036f]/g, '')
        .trim()
        .toLowerCase()
        .replace(/\s+/g, ' ');

    const uniqueMap = (items, resolver) => {
      const counts = new Map();
      (items || []).forEach((item) => {
        const key = resolver(item);
        if (!key) return;
        counts.set(key, (counts.get(key) || 0) + 1);
      });
      const map = new Map();
      (items || []).forEach((item) => {
        const key = resolver(item);
        if (!key || counts.get(key) !== 1) return;
        map.set(key, item);
      });
      return map;
    };

    const rubricKey = (rubric) => {
      const code = normalizeKey(rubric?.codigo);
      if (code) return `code:${code}`;
      const name = normalizeKey(rubric?.nome);
      return name ? `name:${name}` : '';
    };

    const componentKey = (component) => {
      const code = normalizeKey(component?.codigo);
      if (code) return `code:${code}`;
      const name = normalizeKey(component?.nome);
      return name ? `name:${name}` : '';
    };

    const buildPlan = (sourceDomain, targetDomain) => {
      const sourceRubrics = Array.isArray(sourceDomain?.rubricas) ? sourceDomain.rubricas : [];
      const targetRubrics = Array.isArray(targetDomain?.rubricas) ? targetDomain.rubricas : [];
      const sourceMap = uniqueMap(sourceRubrics, rubricKey);
      const targetMap = uniqueMap(targetRubrics, rubricKey);
      const mappings = [];
      let skippedDueToComponentMismatch = 0;
      sourceMap.forEach((sourceRubric, key) => {
        const targetRubric = targetMap.get(key);
        if (!targetRubric) return;
        const sourceComponents = Array.isArray(sourceRubric.components) ? sourceRubric.components : [];
        const targetComponents = Array.isArray(targetRubric.components) ? targetRubric.components : [];
        if (!sourceComponents.length && !targetComponents.length) {
          mappings.push({
            sourceRubricId: String(sourceRubric.id),
            targetRubricId: String(targetRubric.id),
            componentMappings: [],
          });
          return;
        }
        if (!sourceComponents.length || !targetComponents.length) {
          skippedDueToComponentMismatch += 1;
          return;
        }
        const sourceComponentMap = uniqueMap(sourceComponents, componentKey);
        const targetComponentMap = uniqueMap(targetComponents, componentKey);
        const componentMappings = [];
        sourceComponentMap.forEach((sourceComponent, componentMatchKey) => {
          const targetComponent = targetComponentMap.get(componentMatchKey);
          if (!targetComponent) return;
          componentMappings.push({
            sourceId: String(sourceComponent.id),
            targetId: String(targetComponent.id),
          });
        });
        if (componentMappings.length !== sourceComponents.length || componentMappings.length !== targetComponents.length) {
          skippedDueToComponentMismatch += 1;
          return;
        }
        mappings.push({
          sourceRubricId: String(sourceRubric.id),
          targetRubricId: String(targetRubric.id),
          componentMappings,
        });
      });
      return {
        mappings,
        skippedDueToComponentMismatch,
      };
    };

    const rowSupportsMappingWithoutOverride = (row, mapping) => {
      const alunoId = String(row.dataset.alunoId || '');
      if (!alunoId) return false;
      if (mapping.componentMappings.length) {
        const sourceInputs = mapping.componentMappings.map(({ sourceId }) => (
          document.querySelector(`.js-component-score[data-aluno-id="${alunoId}"][data-rubrica-id="${mapping.sourceRubricId}"][data-component-id="${sourceId}"]`)
        ));
        const targetInputs = mapping.componentMappings.map(({ targetId }) => (
          document.querySelector(`.js-component-score[data-aluno-id="${alunoId}"][data-rubrica-id="${mapping.targetRubricId}"][data-component-id="${targetId}"]`)
        ));
        if (sourceInputs.some((input) => !input || input.disabled) || targetInputs.some((input) => !input || input.disabled)) {
          return false;
        }
        return targetInputs[0]?.dataset.overrideActive !== '1';
      }
      const sourceInput = document.querySelector(`.js-student-score[data-aluno-id="${alunoId}"][data-rubrica-id="${mapping.sourceRubricId}"]`);
      const targetInput = document.querySelector(`.js-student-score[data-aluno-id="${alunoId}"][data-rubrica-id="${mapping.targetRubricId}"]`);
      return Boolean(
        sourceInput
        && targetInput
        && !sourceInput.readOnly
        && !targetInput.readOnly
        && !sourceInput.disabled
        && !targetInput.disabled
        && targetInput.dataset.overrideActive !== '1'
      );
    };

    for (const sourceDomain of payload) {
      for (const targetDomain of payload) {
        if (!sourceDomain?.client_id || !targetDomain?.client_id || sourceDomain.client_id === targetDomain.client_id) continue;
        const plan = buildPlan(sourceDomain, targetDomain);
        for (const mapping of plan.mappings) {
          const supportedRows = groupedRows.filter((row) => rowSupportsMappingWithoutOverride(row, mapping));
          if (supportedRows.length < 2) continue;
          return {
            sourceDomainId: sourceDomain.client_id,
            targetDomainId: targetDomain.client_id,
            mapping,
            skippedDueToComponentMismatch: plan.skippedDueToComponentMismatch,
            studentIds: supportedRows.slice(0, 2).map((row) => String(row.dataset.alunoId)),
          };
        }
      }
    }
    return null;
  });
}

async function resolveComponentMismatchScenario(frame) {
  return frame.evaluate(() => {
    const payload = JSON.parse(document.getElementById('avaliacao-domain-copy-config')?.textContent || '[]');
    const row = Array.from(document.querySelectorAll('tr[data-aluno-id][data-presente="1"]'))
      .find((candidate) => !(candidate.dataset.groupId || ''))
      || document.querySelector('tr[data-aluno-id][data-presente="1"]');
    if (!row?.dataset.alunoId) return null;
    const alunoId = String(row.dataset.alunoId);

    const normalizeKey = (rawValue) =>
      String(rawValue || '')
        .normalize('NFD')
        .replace(/[\u0300-\u036f]/g, '')
        .trim()
        .toLowerCase()
        .replace(/\s+/g, ' ');

    const uniqueMap = (items, resolver) => {
      const counts = new Map();
      (items || []).forEach((item) => {
        const key = resolver(item);
        if (!key) return;
        counts.set(key, (counts.get(key) || 0) + 1);
      });
      const map = new Map();
      (items || []).forEach((item) => {
        const key = resolver(item);
        if (!key || counts.get(key) !== 1) return;
        map.set(key, item);
      });
      return map;
    };

    const rubricKey = (rubric) => {
      const code = normalizeKey(rubric?.codigo);
      if (code) return `code:${code}`;
      const name = normalizeKey(rubric?.nome);
      return name ? `name:${name}` : '';
    };

    const componentKey = (component) => {
      const code = normalizeKey(component?.codigo);
      if (code) return `code:${code}`;
      const name = normalizeKey(component?.nome);
      return name ? `name:${name}` : '';
    };

    const describeRubricInputs = (rubricId) => {
      const componentInputs = Array.from(document.querySelectorAll(`.js-component-score[data-aluno-id="${alunoId}"][data-rubrica-id="${rubricId}"][data-component-id]`))
        .filter((input) => !input.disabled);
      if (componentInputs.length) {
        return {
          mode: 'components',
          selectors: componentInputs.map((input) => `.js-component-score[data-aluno-id="${alunoId}"][data-rubrica-id="${rubricId}"][data-component-id="${input.dataset.componentId}"]`),
        };
      }
      const directSelector = `.js-student-score[data-aluno-id="${alunoId}"][data-rubrica-id="${rubricId}"]`;
      const directInput = document.querySelector(directSelector);
      if (directInput && !directInput.readOnly && !directInput.disabled) {
        return { mode: 'direct', selectors: [directSelector] };
      }
      if (!componentInputs.length) return null;
      return {
        mode: 'components',
        selectors: componentInputs.map((input) => `.js-component-score[data-aluno-id="${alunoId}"][data-rubrica-id="${rubricId}"][data-component-id="${input.dataset.componentId}"]`),
      };
    };

    for (const sourceDomain of payload) {
      for (const targetDomain of payload) {
        if (!sourceDomain?.client_id || !targetDomain?.client_id || sourceDomain.client_id === targetDomain.client_id) continue;
        const sourceMap = uniqueMap(Array.isArray(sourceDomain?.rubricas) ? sourceDomain.rubricas : [], rubricKey);
        const targetMap = uniqueMap(Array.isArray(targetDomain?.rubricas) ? targetDomain.rubricas : [], rubricKey);
        let usableMapping = null;
        let incompatibleRubric = null;

        sourceMap.forEach((sourceRubric, key) => {
          const targetRubric = targetMap.get(key);
          if (!targetRubric) return;
          const sourceComponents = Array.isArray(sourceRubric.components) ? sourceRubric.components : [];
          const targetComponents = Array.isArray(targetRubric.components) ? targetRubric.components : [];
          if (!sourceComponents.length && !targetComponents.length) {
            if (!usableMapping) {
              usableMapping = {
                sourceRubricId: String(sourceRubric.id),
                targetRubricId: String(targetRubric.id),
                componentMappings: [],
              };
            }
            return;
          }
          if (!sourceComponents.length || !targetComponents.length) {
            const sourceInputs = describeRubricInputs(String(sourceRubric.id));
            const targetInputs = describeRubricInputs(String(targetRubric.id));
            if (!incompatibleRubric && sourceInputs && targetInputs) {
              incompatibleRubric = {
                sourceRubricId: String(sourceRubric.id),
                targetRubricId: String(targetRubric.id),
                sourceInputs,
                targetInputs,
              };
            }
            return;
          }
          const sourceComponentMap = uniqueMap(sourceComponents, componentKey);
          const targetComponentMap = uniqueMap(targetComponents, componentKey);
          const componentMappings = [];
          sourceComponentMap.forEach((sourceComponent, componentMatchKey) => {
            const targetComponent = targetComponentMap.get(componentMatchKey);
            if (!targetComponent) return;
            componentMappings.push({
              sourceId: String(sourceComponent.id),
              targetId: String(targetComponent.id),
            });
          });
          if (componentMappings.length !== sourceComponents.length || componentMappings.length !== targetComponents.length) {
            const sourceInputs = describeRubricInputs(String(sourceRubric.id));
            const targetInputs = describeRubricInputs(String(targetRubric.id));
            if (!incompatibleRubric && sourceInputs && targetInputs) {
              incompatibleRubric = {
                sourceRubricId: String(sourceRubric.id),
                targetRubricId: String(targetRubric.id),
                sourceInputs,
                targetInputs,
              };
            }
            return;
          }
          if (!usableMapping && componentMappings.length) {
            usableMapping = {
              sourceRubricId: String(sourceRubric.id),
              targetRubricId: String(targetRubric.id),
              componentMappings,
            };
          }
        });

        if (usableMapping && incompatibleRubric) {
          return {
            alunoId,
            sourceDomainId: sourceDomain.client_id,
            targetDomainId: targetDomain.client_id,
            usableMapping,
            incompatibleRubric,
          };
        }
      }
    }
    return null;
  });
}

async function resolveFillScenario(frame) {
  return frame.evaluate(() => {
    const table = document.getElementById('avaliacao-objeto-table');
    const baseFillValue = Number(table?.dataset.baseFillValue || 3) || 3;
    const allSimpleInputs = Array.from(document.querySelectorAll('.js-student-score:not(:disabled)'))
      .filter((input) => !document.querySelector(`.js-component-score[data-aluno-id="${input.dataset.alunoId}"][data-rubrica-id="${input.dataset.rubricaId}"][data-component-id]`));
    const preferredInputs = allSimpleInputs.filter((input) => {
      const row = input.closest('tr[data-aluno-id]');
      return row && !(row.dataset.groupId || '');
    });
    const candidateInputs = preferredInputs.length >= 2 ? preferredInputs : allSimpleInputs;
    if (candidateInputs.length < 2) return null;
    const [blankInput, filledInput] = candidateInputs;
    return {
      baseFillValue,
      blankSelector: `.js-student-score[data-aluno-id="${blankInput.dataset.alunoId}"][data-rubrica-id="${blankInput.dataset.rubricaId}"]`,
      filledSelector: `.js-student-score[data-aluno-id="${filledInput.dataset.alunoId}"][data-rubrica-id="${filledInput.dataset.rubricaId}"]`,
    };
  });
}

async function resolveRubricShortcutScenario(frame) {
  return frame.evaluate(() => {
    const allRows = Array.from(document.querySelectorAll('tr[data-aluno-id][data-presente="1"]'));
    const preferredRows = allRows.filter((row) => !(row.dataset.groupId || ''));
    const candidateRows = preferredRows.length ? preferredRows : allRows;

    const findSimpleInput = () => {
      const allDirectInputs = Array.from(document.querySelectorAll('.js-student-score[data-aluno-id][data-rubrica-id]'))
        .filter((input) => !input.disabled);
      const preferredInputs = allDirectInputs.filter((input) => {
        const row = input.closest('tr[data-aluno-id]');
        if (!row || (row.dataset.groupId || '')) return false;
        return !document.querySelector(`.js-component-score[data-aluno-id="${input.dataset.alunoId}"][data-rubrica-id="${input.dataset.rubricaId}"][data-component-id]`);
      });
      const fallbackInputs = allDirectInputs.filter((input) => (
        !document.querySelector(`.js-component-score[data-aluno-id="${input.dataset.alunoId}"][data-rubrica-id="${input.dataset.rubricaId}"][data-component-id]`)
      ));
      return preferredInputs[0] || fallbackInputs[0] || null;
    };

    const simpleInput = findSimpleInput();

    for (const row of candidateRows) {
      const alunoId = String(row.dataset.alunoId || '');
      const rubricInputs = Array.from(row.querySelectorAll('.js-student-score[data-aluno-id][data-rubrica-id]'))
        .filter((input) => !input.disabled);
      for (const rubricInput of rubricInputs) {
        const rubricaId = String(rubricInput.dataset.rubricaId || '');
        const componentInputs = Array.from(document.querySelectorAll(`.js-component-score[data-aluno-id="${alunoId}"][data-rubrica-id="${rubricaId}"][data-component-id]`))
          .filter((input) => !input.disabled);
        if (componentInputs.length < 2) continue;
        return {
          alunoId,
          rubricaId,
          rubricSelector: `.js-student-score[data-aluno-id="${alunoId}"][data-rubrica-id="${rubricaId}"]`,
          componentSelectors: componentInputs.map((input) => `.js-component-score[data-aluno-id="${alunoId}"][data-rubrica-id="${rubricaId}"][data-component-id="${input.dataset.componentId}"]`),
          simpleRubricSelector: simpleInput
            ? `.js-student-score[data-aluno-id="${simpleInput.dataset.alunoId}"][data-rubrica-id="${simpleInput.dataset.rubricaId}"]`
            : null,
        };
      }
    }
    return null;
  });
}

async function resolveKeyboardNavigationScenario(frame) {
  return frame.evaluate(() => {
    const isVisibleInput = (input) => (
      !input.disabled
      && !input.closest('.dominio-collapsed')
      && input.getClientRects().length > 0
    );

    const selectorFor = (input) => {
      if (!input) return null;
      if (input.classList.contains('js-component-score')) {
        return `.js-component-score[data-aluno-id="${input.dataset.alunoId}"][data-rubrica-id="${input.dataset.rubricaId}"][data-component-id="${input.dataset.componentId}"]`;
      }
      if (input.classList.contains('js-student-score')) {
        return `.js-student-score[data-aluno-id="${input.dataset.alunoId}"][data-rubrica-id="${input.dataset.rubricaId}"]`;
      }
      return null;
    };

    const allRows = Array.from(document.querySelectorAll('tr[data-aluno-id][data-presente="1"]'))
      .map((row) => ({
        row,
        inputs: Array.from(row.querySelectorAll('input.avaliacao-input')).filter(isVisibleInput),
      }))
      .filter((entry) => entry.inputs.length > 0);

    const preferredRows = allRows.filter((entry) => !(entry.row.dataset.groupId || ''));
    const candidateRows = preferredRows.length >= 2 ? preferredRows : allRows;
    if (candidateRows.length < 2) return null;

    const [firstRow, secondRow] = candidateRows;
    const sharedColumnCount = Math.min(firstRow.inputs.length, secondRow.inputs.length);
    if (sharedColumnCount < 2) return null;

    const simpleIndex = firstRow.inputs.findIndex((input, index) => {
      if (index + 1 >= sharedColumnCount) return false;
      if (!input.classList.contains('js-student-score')) return false;
      return !document.querySelector(`.js-component-score[data-aluno-id="${input.dataset.alunoId}"][data-rubrica-id="${input.dataset.rubricaId}"][data-component-id]`);
    });
    const componentIndex = firstRow.inputs.findIndex((input, index) => (
      index < sharedColumnCount && input.classList.contains('js-component-score')
    ));
    if (simpleIndex === -1 || componentIndex === -1) return null;

    const domainGroups = [];
    firstRow.inputs.forEach((input, index) => {
      const domainId = input.closest('td.dominio-rubrica-coluna[data-domain-id]')?.dataset.domainId || '';
      if (!domainId) return;
      const lastGroup = domainGroups[domainGroups.length - 1];
      if (!lastGroup || lastGroup.domainId !== domainId) {
        domainGroups.push({ domainId, startIndex: index, endIndex: index });
        return;
      }
      lastGroup.endIndex = index;
    });

    let collapseScenario = null;
    for (let index = 1; index < domainGroups.length - 1; index += 1) {
      const previousGroup = domainGroups[index - 1];
      const targetGroup = domainGroups[index];
      const nextGroup = domainGroups[index + 1];
      const beforeInput = firstRow.inputs[previousGroup.endIndex];
      const hiddenInput = firstRow.inputs[targetGroup.startIndex];
      const afterInput = firstRow.inputs[nextGroup.startIndex];
      if (!beforeInput || !hiddenInput || !afterInput) continue;
      collapseScenario = {
        domainId: targetGroup.domainId,
        toggleSelector: `.dominio-toggle[data-domain-id="${targetGroup.domainId}"]`,
        beforeSelector: selectorFor(beforeInput),
        hiddenSelector: selectorFor(hiddenInput),
        afterSelector: selectorFor(afterInput),
      };
      break;
    }
    if (!collapseScenario) return null;

    const simpleCurrent = firstRow.inputs[simpleIndex];
    const simpleRight = firstRow.inputs[simpleIndex + 1];
    const simpleDown = secondRow.inputs[Math.min(simpleIndex, secondRow.inputs.length - 1)];
    const componentCurrent = firstRow.inputs[componentIndex];
    const componentDown = secondRow.inputs[Math.min(componentIndex, secondRow.inputs.length - 1)];

    if (!simpleCurrent || !simpleRight || !simpleDown || !componentCurrent || !componentDown) {
      return null;
    }

    return {
      simple: {
        currentSelector: selectorFor(simpleCurrent),
        rightSelector: selectorFor(simpleRight),
        downSelector: selectorFor(simpleDown),
      },
      component: {
        currentSelector: selectorFor(componentCurrent),
        downSelector: selectorFor(componentDown),
      },
      collapseScenario,
    };
  });
}

async function seedCopyValues(frameLocator, scenario, studentIds) {
  if (scenario.mapping.componentMappings.length) {
    const sourceValues = ['4', '5'];
    const targetValues = ['1', '1'];
    const expectedValuesByTargetId = {};
    for (const alunoId of studentIds) {
      for (let index = 0; index < scenario.mapping.componentMappings.length; index += 1) {
        const componentMapping = scenario.mapping.componentMappings[index];
        const sourceValue = sourceValues[index] || '4';
        const targetValue = targetValues[index] || '1';
        await frameLocator.locator(componentSelector(alunoId, scenario.mapping.sourceRubricId, componentMapping.sourceId)).fill(sourceValue);
        await frameLocator.locator(componentSelector(alunoId, scenario.mapping.targetRubricId, componentMapping.targetId)).fill(targetValue);
        expectedValuesByTargetId[componentMapping.targetId] = sourceValue;
      }
    }
    return { expectedValuesByTargetId };
  }

  for (const alunoId of studentIds) {
    await frameLocator.locator(studentRubricSelector(alunoId, scenario.mapping.sourceRubricId)).fill('4.5');
    await frameLocator.locator(studentRubricSelector(alunoId, scenario.mapping.targetRubricId)).fill('1');
  }
  return { expectedValuesByTargetId: { direct: '4.5' } };
}

async function seedCopySourceValues(frameLocator, scenario, studentIds) {
  if (scenario.mapping.componentMappings.length) {
    const sourceValues = ['4', '5'];
    const expectedValuesByTargetId = {};
    for (const alunoId of studentIds) {
      for (let index = 0; index < scenario.mapping.componentMappings.length; index += 1) {
        const componentMapping = scenario.mapping.componentMappings[index];
        const sourceValue = sourceValues[index] || '4';
        await frameLocator.locator(componentSelector(alunoId, scenario.mapping.sourceRubricId, componentMapping.sourceId)).fill(sourceValue);
        expectedValuesByTargetId[componentMapping.targetId] = sourceValue;
      }
    }
    return { expectedValuesByTargetId };
  }

  for (const alunoId of studentIds) {
    await frameLocator.locator(studentRubricSelector(alunoId, scenario.mapping.sourceRubricId)).fill('4.5');
  }
  return { expectedValuesByTargetId: { direct: '4.5' } };
}

async function getSelectedCopyTargetLabel(frameLocator, sourceDomainId) {
  return frameLocator
    .locator(`.js-domain-copy-target[data-source-domain-id="${sourceDomainId}"]`)
    .evaluate((select) => select.options[select.selectedIndex]?.textContent || '');
}

async function readTargetRubricValues(frameLocator, alunoId, mapping) {
  if (mapping.componentMappings.length) {
    const values = {};
    for (const componentMapping of mapping.componentMappings) {
      values[componentMapping.targetId] = await frameLocator
        .locator(componentSelector(alunoId, mapping.targetRubricId, componentMapping.targetId))
        .inputValue();
    }
    return { mode: 'components', values };
  }
  return {
    mode: 'direct',
    value: await frameLocator.locator(studentRubricSelector(alunoId, mapping.targetRubricId)).inputValue(),
  };
}

async function expectTargetRubricValues(frameLocator, alunoId, mapping, expected) {
  if (expected.mode === 'components') {
    for (const componentMapping of mapping.componentMappings) {
      await expect(
        frameLocator.locator(componentSelector(alunoId, mapping.targetRubricId, componentMapping.targetId))
      ).toHaveValue(expected.values[componentMapping.targetId] || '');
    }
    return;
  }
  await expect(frameLocator.locator(studentRubricSelector(alunoId, mapping.targetRubricId))).toHaveValue(expected.value || '');
}

async function openCopyControls(frameLocator, sourceDomainId) {
  const summary = frameLocator.locator(`.js-domain-copy-menu[data-source-domain-id="${sourceDomainId}"] summary`);
  if (await summary.count()) {
    await summary.click();
  }
}

test('abre /aula/48/avaliacao e regista screenshot da grelha', async ({ page }, testInfo) => {
  const { frameLocator } = await openAvaliacao(page);

  await expect(frameLocator.locator('#avaliacao-save-button')).toBeVisible();
  await expect(frameLocator.locator('#avaliacao-fill-empty-button')).toBeVisible();
  await expect(frameLocator.locator('.js-domain-copy-menu').first()).toBeVisible();

  const screenshotPath = testInfo.outputPath('aula-48-avaliacao.png');
  await page.screenshot({
    path: screenshotPath,
    fullPage: true,
  });

  testInfo.annotations.push({
    type: 'screenshot',
    description: screenshotPath,
  });
});

test('copia dominio compativel para o aluno atual sem autosave e guarda no fim', async ({ page }) => {
  const requests = attachPostCounter(page);
  const { frame, frameLocator } = await openAvaliacao(page);
  const scenario = await resolveCopyScenario(frame, 1);

  expect(scenario).toBeTruthy();

  const alunoId = scenario.studentIds[0];
  const seededValues = await seedCopyValues(frameLocator, scenario, [alunoId]);

  const focusSelector = scenario.mapping.componentMappings.length
    ? componentSelector(alunoId, scenario.mapping.sourceRubricId, scenario.mapping.componentMappings[0].sourceId)
    : studentRubricSelector(alunoId, scenario.mapping.sourceRubricId);

  await frameLocator.locator(focusSelector).click();
  await openCopyControls(frameLocator, scenario.sourceDomainId);
  await frameLocator.locator(`.js-domain-copy-target[data-source-domain-id="${scenario.sourceDomainId}"]`).selectOption(scenario.targetDomainId);
  expect(await getSelectedCopyTargetLabel(frameLocator, scenario.sourceDomainId)).toMatch(/compat/i);
  await expect(frameLocator.locator(`.js-domain-copy-menu[data-source-domain-id="${scenario.sourceDomainId}"] .js-domain-copy-note`)).toHaveCount(0);
  await frameLocator.locator(`.js-domain-copy-current[data-source-domain-id="${scenario.sourceDomainId}"]`).click();

  if (scenario.mapping.componentMappings.length) {
    for (const componentMapping of scenario.mapping.componentMappings) {
      await expect(
        frameLocator.locator(componentSelector(alunoId, scenario.mapping.targetRubricId, componentMapping.targetId))
      ).toHaveValue(seededValues.expectedValuesByTargetId[componentMapping.targetId]);
    }

    const editedComponent = scenario.mapping.componentMappings[0];
    await frameLocator.locator(componentSelector(alunoId, scenario.mapping.targetRubricId, editedComponent.targetId)).fill('2');
    await expect(frameLocator.locator(componentSelector(alunoId, scenario.mapping.targetRubricId, editedComponent.targetId))).toHaveValue('2');
  } else {
    await expect(frameLocator.locator(studentRubricSelector(alunoId, scenario.mapping.targetRubricId))).toHaveValue('4.5');
    await frameLocator.locator(studentRubricSelector(alunoId, scenario.mapping.targetRubricId)).fill('2.5');
    await expect(frameLocator.locator(studentRubricSelector(alunoId, scenario.mapping.targetRubricId))).toHaveValue('2.5');
  }

  await page.waitForTimeout(900);
  expect(requests.count).toBe(0);
  await expect(frameLocator.locator('#avaliacao-save-button')).toHaveText('Guardar *');

  await frameLocator.locator('#avaliacao-save-button').click();
  await expect(frameLocator.locator('#avaliacao-save-button')).toHaveText('Guardado', { timeout: 10_000 });
  await expect.poll(() => requests.count).toBe(1);

  const reopened = await openAvaliacao(page);
  if (scenario.mapping.componentMappings.length) {
    const editedComponent = scenario.mapping.componentMappings[0];
    await expect(reopened.frameLocator.locator(componentSelector(alunoId, scenario.mapping.targetRubricId, editedComponent.targetId))).toHaveValue('2');
  } else {
    await expect(reopened.frameLocator.locator(studentRubricSelector(alunoId, scenario.mapping.targetRubricId))).toHaveValue('2.5');
  }
});

test('nao copia rubrica com componentes incompatíveis', async ({ page }) => {
  const { frame, frameLocator } = await openAvaliacao(page);
  const scenario = await resolveComponentMismatchScenario(frame);

  expect(scenario).toBeTruthy();

  const currentTargetValues = [];
  for (const selector of scenario.incompatibleRubric.targetInputs.selectors) {
    currentTargetValues.push(await frameLocator.locator(selector).inputValue());
  }

  if (scenario.incompatibleRubric.sourceInputs.mode === 'direct') {
    await frameLocator.locator(scenario.incompatibleRubric.sourceInputs.selectors[0]).fill('4.5');
  } else {
    for (const [index, selector] of scenario.incompatibleRubric.sourceInputs.selectors.entries()) {
      await frameLocator.locator(selector).fill(String((index % 2) + 4));
    }
  }

  if (scenario.incompatibleRubric.targetInputs.mode === 'direct') {
    await frameLocator.locator(scenario.incompatibleRubric.targetInputs.selectors[0]).fill('1.5');
  } else {
    for (const [index, selector] of scenario.incompatibleRubric.targetInputs.selectors.entries()) {
      await frameLocator.locator(selector).fill(String((index % 2) + 1));
    }
  }

  const expectedTargetValues = [];
  for (const selector of scenario.incompatibleRubric.targetInputs.selectors) {
    expectedTargetValues.push(await frameLocator.locator(selector).inputValue());
  }

  const focusSelector = scenario.usableMapping.componentMappings.length
    ? componentSelector(scenario.alunoId, scenario.usableMapping.sourceRubricId, scenario.usableMapping.componentMappings[0].sourceId)
    : studentRubricSelector(scenario.alunoId, scenario.usableMapping.sourceRubricId);

  await frameLocator.locator(focusSelector).click();
  await openCopyControls(frameLocator, scenario.sourceDomainId);
  await frameLocator.locator(`.js-domain-copy-target[data-source-domain-id="${scenario.sourceDomainId}"]`).selectOption(scenario.targetDomainId);
  expect(await getSelectedCopyTargetLabel(frameLocator, scenario.sourceDomainId)).toMatch(/compat/i);
  expect(await getSelectedCopyTargetLabel(frameLocator, scenario.sourceDomainId)).toMatch(/incompat/i);
  await expect(frameLocator.locator(`.js-domain-copy-menu[data-source-domain-id="${scenario.sourceDomainId}"] .js-domain-copy-note`)).toHaveCount(0);
  await frameLocator.locator(`.js-domain-copy-current[data-source-domain-id="${scenario.sourceDomainId}"]`).click();

  for (const [index, selector] of scenario.incompatibleRubric.targetInputs.selectors.entries()) {
    await expect(frameLocator.locator(selector)).toHaveValue(expectedTargetValues[index] || currentTargetValues[index] || '');
  }
});

test('copia dominio para todos e preenche vazias com valor base sem autosave', async ({ page }) => {
  const requests = attachPostCounter(page);
  const { frame, frameLocator } = await openAvaliacao(page);
  const scenario = await resolveCopyScenario(frame, 2);
  const fillScenario = await resolveFillScenario(frame);

  expect(scenario).toBeTruthy();
  expect(fillScenario).toBeTruthy();

  const seededValues = await seedCopyValues(frameLocator, scenario, scenario.studentIds);

  await openCopyControls(frameLocator, scenario.sourceDomainId);
  await frameLocator.locator(`.js-domain-copy-target[data-source-domain-id="${scenario.sourceDomainId}"]`).selectOption(scenario.targetDomainId);
  await frameLocator.locator(`.js-domain-copy-all[data-source-domain-id="${scenario.sourceDomainId}"]`).click();

  for (const alunoId of scenario.studentIds) {
    if (scenario.mapping.componentMappings.length) {
      for (const componentMapping of scenario.mapping.componentMappings) {
        await expect(
          frameLocator.locator(componentSelector(alunoId, scenario.mapping.targetRubricId, componentMapping.targetId))
        ).toHaveValue(seededValues.expectedValuesByTargetId[componentMapping.targetId]);
      }
    } else {
      await expect(frameLocator.locator(studentRubricSelector(alunoId, scenario.mapping.targetRubricId))).toHaveValue('4.5');
    }
  }

  await frameLocator.locator(fillScenario.filledSelector).fill('1.5');
  await frameLocator.locator(fillScenario.blankSelector).fill('');
  await frameLocator.locator('#avaliacao-fill-empty-button').click();

  await expect(frameLocator.locator(fillScenario.filledSelector)).toHaveValue('1.5');
  await expect(frameLocator.locator(fillScenario.blankSelector)).toHaveValue(numericValuePattern(fillScenario.baseFillValue));

  await page.waitForTimeout(900);
  expect(requests.count).toBe(0);
  await expect(frameLocator.locator('#avaliacao-save-button')).toHaveText('Guardar *');

  await frameLocator.locator('#avaliacao-save-button').click();
  await expect(frameLocator.locator('#avaliacao-save-button')).toHaveText('Guardado', { timeout: 10_000 });
  await expect.poll(() => requests.count).toBe(1);

  const reopened = await openAvaliacao(page);
  await expect(reopened.frameLocator.locator(fillScenario.filledSelector)).toHaveValue('1.5');
  await expect(reopened.frameLocator.locator(fillScenario.blankSelector)).toHaveValue(numericValuePattern(fillScenario.baseFillValue));
});

test('usa a rubrica como atalho para preencher componentes vazios sem sobrescrever os existentes', async ({ page }) => {
  const requests = attachPostCounter(page);
  const { frame, frameLocator } = await openAvaliacao(page);
  const scenario = await resolveRubricShortcutScenario(frame);

  expect(scenario).toBeTruthy();

  for (const selector of scenario.componentSelectors) {
    await frameLocator.locator(selector).fill('');
  }
  await frameLocator.locator(scenario.rubricSelector).fill('3');
  await frameLocator.locator(scenario.rubricSelector).press('Tab');

  for (const selector of scenario.componentSelectors) {
    await expect(frameLocator.locator(selector)).toHaveValue('3');
  }
  await expect(frameLocator.locator(scenario.rubricSelector)).toHaveValue('3.00');

  await frameLocator.locator(scenario.componentSelectors[0]).fill('4');
  for (const selector of scenario.componentSelectors.slice(1)) {
    await frameLocator.locator(selector).fill('');
  }
  await frameLocator.locator(scenario.rubricSelector).fill('3');
  await frameLocator.locator(scenario.rubricSelector).press('Tab');

  await expect(frameLocator.locator(scenario.componentSelectors[0])).toHaveValue('4');
  for (const selector of scenario.componentSelectors.slice(1)) {
    await expect(frameLocator.locator(selector)).toHaveValue('3');
  }

  const afterShortcutAverage = ((4 + (3 * (scenario.componentSelectors.length - 1))) / scenario.componentSelectors.length).toFixed(2);
  await expect(frameLocator.locator(scenario.rubricSelector)).toHaveValue(afterShortcutAverage);

  const lastComponentSelector = scenario.componentSelectors[scenario.componentSelectors.length - 1];
  await frameLocator.locator(lastComponentSelector).fill('5');
  await expect(frameLocator.locator(lastComponentSelector)).toHaveValue('5');

  const afterManualAverage = ((4 + (3 * Math.max(0, scenario.componentSelectors.length - 2)) + 5) / scenario.componentSelectors.length).toFixed(2);
  await expect(frameLocator.locator(scenario.rubricSelector)).toHaveValue(afterManualAverage);

  if (scenario.simpleRubricSelector) {
    await frameLocator.locator(scenario.simpleRubricSelector).fill('2.5');
    await frameLocator.locator(scenario.simpleRubricSelector).press('Tab');
    await expect(frameLocator.locator(scenario.simpleRubricSelector)).toHaveValue('2.5');
  }

  await page.waitForTimeout(900);
  expect(requests.count).toBe(0);
  await expect(frameLocator.locator('#avaliacao-save-button')).toHaveText('Guardar *');

  await frameLocator.locator('#avaliacao-save-button').click();
  await expect(frameLocator.locator('#avaliacao-save-button')).toHaveText('Guardado', { timeout: 10_000 });
  await expect.poll(() => requests.count).toBe(1);

  const reopened = await openAvaliacao(page);
  await expect(reopened.frameLocator.locator(scenario.componentSelectors[0])).toHaveValue('4');
  for (const selector of scenario.componentSelectors.slice(1, -1)) {
    await expect(reopened.frameLocator.locator(selector)).toHaveValue('3');
  }
  await expect(reopened.frameLocator.locator(lastComponentSelector)).toHaveValue('5');
  await expect(reopened.frameLocator.locator(scenario.rubricSelector)).toHaveValue(numericValuePattern(afterManualAverage));
  if (scenario.simpleRubricSelector) {
    await expect(reopened.frameLocator.locator(scenario.simpleRubricSelector)).toHaveValue(numericValuePattern('2.5'));
  }
});

test('navega na grelha com teclado e ignora colunas colapsadas sem impactar o save', async ({ page }) => {
  const requests = attachPostCounter(page);
  const consoleErrors = attachConsoleErrorTracker(page);
  const { frame, frameLocator } = await openAvaliacao(page);
  const scenario = await resolveKeyboardNavigationScenario(frame);

  expect(scenario).toBeTruthy();

  const simpleCurrent = frameLocator.locator(scenario.simple.currentSelector);
  const simpleRight = frameLocator.locator(scenario.simple.rightSelector);
  const simpleDown = frameLocator.locator(scenario.simple.downSelector);
  const componentCurrent = frameLocator.locator(scenario.component.currentSelector);
  const componentDown = frameLocator.locator(scenario.component.downSelector);

  await simpleCurrent.click();
  await expect(simpleCurrent).toBeFocused();
  await simpleCurrent.press('ArrowRight');
  await expect(simpleRight).toBeFocused();
  await simpleRight.press('ArrowLeft');
  await expect(simpleCurrent).toBeFocused();

  await simpleCurrent.press('Tab');
  await expect(simpleRight).toBeFocused();
  await simpleRight.press('Shift+Tab');
  await expect(simpleCurrent).toBeFocused();

  await simpleCurrent.press('Enter');
  await expect(simpleDown).toBeFocused();

  await componentCurrent.click();
  await expect(componentCurrent).toBeFocused();
  await componentCurrent.press('ArrowDown');
  await expect(componentDown).toBeFocused();
  await componentDown.press('ArrowUp');
  await expect(componentCurrent).toBeFocused();

  await simpleCurrent.fill('2.5');
  await componentCurrent.fill('4');

  await page.waitForTimeout(500);
  expect(requests.count).toBe(0);
  await expect(frameLocator.locator('#avaliacao-save-button')).toHaveText('Guardar *');

  await frameLocator.locator(scenario.collapseScenario.toggleSelector).click();
  await expect(frameLocator.locator(scenario.collapseScenario.hiddenSelector)).not.toBeVisible();
  const beforeCollapsedDomain = frameLocator.locator(scenario.collapseScenario.beforeSelector);
  const afterCollapsedDomain = frameLocator.locator(scenario.collapseScenario.afterSelector);
  await beforeCollapsedDomain.click();
  await beforeCollapsedDomain.press('ArrowRight');
  await expect(afterCollapsedDomain).toBeFocused();

  expect(consoleErrors.messages).toEqual([]);

  await frameLocator.locator('#avaliacao-save-button').click();
  await expect(frameLocator.locator('#avaliacao-save-button')).toHaveText('Guardado', { timeout: 10_000 });
  await expect.poll(() => requests.count).toBe(1);

  const reopened = await openAvaliacao(page);
  await expect(reopened.frameLocator.locator(scenario.simple.currentSelector)).toHaveValue(numericValuePattern('2.5'));
  await expect(reopened.frameLocator.locator(scenario.component.currentSelector)).toHaveValue('4');
});

test('aplica atalhos rapidos de edicao sem autosave e preserva o save por botao', async ({ page }) => {
  const requests = attachPostCounter(page);
  const consoleErrors = attachConsoleErrorTracker(page);
  const { frame, frameLocator } = await openAvaliacao(page);
  const scenario = await resolveKeyboardNavigationScenario(frame);

  expect(scenario).toBeTruthy();

  const simpleCurrent = frameLocator.locator(scenario.simple.currentSelector);
  const componentCurrent = frameLocator.locator(scenario.component.currentSelector);

  await simpleCurrent.click();
  await simpleCurrent.press('2');
  await expect(simpleCurrent).toHaveValue(numericValuePattern('2'));
  await simpleCurrent.press('+');
  await expect(simpleCurrent).toHaveValue(numericValuePattern('3'));
  await simpleCurrent.press('-');
  await expect(simpleCurrent).toHaveValue(numericValuePattern('2'));
  await simpleCurrent.press('Delete');
  await expect(simpleCurrent).toHaveValue('');
  await simpleCurrent.press('4');
  await expect(simpleCurrent).toHaveValue(numericValuePattern('4'));
  await simpleCurrent.press('Backspace');
  await expect(simpleCurrent).toHaveValue('');
  await simpleCurrent.press('4');
  await expect(simpleCurrent).toHaveValue(numericValuePattern('4'));

  await componentCurrent.click();
  await componentCurrent.press('9');
  await expect(componentCurrent).toHaveValue('5');
  await componentCurrent.press('-');
  await expect(componentCurrent).toHaveValue('4');
  await componentCurrent.press('+');
  await expect(componentCurrent).toHaveValue('5');
  await componentCurrent.press('Backspace');
  await expect(componentCurrent).toHaveValue('');
  await componentCurrent.press('4');
  await expect(componentCurrent).toHaveValue('4');

  await page.waitForTimeout(500);
  expect(requests.count).toBe(0);
  expect(consoleErrors.messages).toEqual([]);
  await expect(frameLocator.locator('#avaliacao-save-button')).toHaveText('Guardar *');

  await frameLocator.locator('#avaliacao-save-button').click();
  await expect(frameLocator.locator('#avaliacao-save-button')).toHaveText('Guardado', { timeout: 10_000 });
  await expect.poll(() => requests.count).toBe(1);

  const reopened = await openAvaliacao(page);
  await expect(reopened.frameLocator.locator(scenario.simple.currentSelector)).toHaveValue(numericValuePattern('4'));
  await expect(reopened.frameLocator.locator(scenario.component.currentSelector)).toHaveValue('4');
});

test('preserva overrides individuais na copia de dominio para aluno atual e todos', async ({ page }) => {
  const requests = attachPostCounter(page);
  const { frame, frameLocator } = await openAvaliacao(page);
  const scenario = await resolveGroupedOverrideCopyScenario(frame);

  expect(scenario).toBeTruthy();

  const [overrideAlunoId, copiedAlunoId] = scenario.studentIds;
  const seededSourceValues = await seedCopySourceValues(frameLocator, scenario, scenario.studentIds);
  const selectLocator = frameLocator.locator(`.js-domain-copy-target[data-source-domain-id="${scenario.sourceDomainId}"]`);

  await openCopyControls(frameLocator, scenario.sourceDomainId);
  await selectLocator.selectOption(scenario.targetDomainId);
  expect(await getSelectedCopyTargetLabel(frameLocator, scenario.sourceDomainId)).toMatch(/compat/i);
  await expect(frameLocator.locator(`.js-domain-copy-menu[data-source-domain-id="${scenario.sourceDomainId}"] .js-domain-copy-note`)).toHaveCount(0);

  if (scenario.mapping.componentMappings.length) {
    const protectedComponentId = scenario.mapping.componentMappings[0].targetId;
    await frameLocator.locator(componentSelector(overrideAlunoId, scenario.mapping.targetRubricId, protectedComponentId)).fill('2');
    await expect(
      frameLocator.locator(componentSelector(overrideAlunoId, scenario.mapping.targetRubricId, protectedComponentId))
    ).toHaveAttribute('data-override-active', '1');
  } else {
    await frameLocator.locator(studentRubricSelector(overrideAlunoId, scenario.mapping.targetRubricId)).fill('2.25');
    await expect(
      frameLocator.locator(studentRubricSelector(overrideAlunoId, scenario.mapping.targetRubricId))
    ).toHaveAttribute('data-override-active', '1');
  }

  const preservedBeforeCurrentCopy = await readTargetRubricValues(frameLocator, overrideAlunoId, scenario.mapping);
  const untouchedBeforeCurrentCopy = await readTargetRubricValues(frameLocator, copiedAlunoId, scenario.mapping);
  const focusSelector = scenario.mapping.componentMappings.length
    ? componentSelector(overrideAlunoId, scenario.mapping.sourceRubricId, scenario.mapping.componentMappings[0].sourceId)
    : studentRubricSelector(overrideAlunoId, scenario.mapping.sourceRubricId);

  await frameLocator.locator(focusSelector).click();
  await frameLocator.locator(`.js-domain-copy-current[data-source-domain-id="${scenario.sourceDomainId}"]`).click();

  await expect(frameLocator.locator('#avaliacao-action-status')).toContainText('mantido');
  await expectTargetRubricValues(frameLocator, overrideAlunoId, scenario.mapping, preservedBeforeCurrentCopy);
  await expectTargetRubricValues(frameLocator, copiedAlunoId, scenario.mapping, untouchedBeforeCurrentCopy);

  await openCopyControls(frameLocator, scenario.sourceDomainId);
  await selectLocator.selectOption(scenario.targetDomainId);
  await frameLocator.locator(`.js-domain-copy-all[data-source-domain-id="${scenario.sourceDomainId}"]`).click();

  await expect(frameLocator.locator('#avaliacao-action-status')).toContainText('copiado para');
  await expect(frameLocator.locator('#avaliacao-action-status')).toContainText('mantido');
  await expectTargetRubricValues(frameLocator, overrideAlunoId, scenario.mapping, preservedBeforeCurrentCopy);

  if (scenario.mapping.componentMappings.length) {
    for (const componentMapping of scenario.mapping.componentMappings) {
      await expect(
        frameLocator.locator(componentSelector(copiedAlunoId, scenario.mapping.targetRubricId, componentMapping.targetId))
      ).toHaveValue(seededSourceValues.expectedValuesByTargetId[componentMapping.targetId]);
    }
  } else {
    await expect(frameLocator.locator(studentRubricSelector(copiedAlunoId, scenario.mapping.targetRubricId))).toHaveValue('4.5');
  }

  await page.waitForTimeout(900);
  expect(requests.count).toBe(0);
  await expect(frameLocator.locator('#avaliacao-save-button')).toHaveText('Guardar *');

  await frameLocator.locator('#avaliacao-save-button').click();
  await expect(frameLocator.locator('#avaliacao-save-button')).toHaveText('Guardado', { timeout: 10_000 });
  await expect.poll(() => requests.count).toBe(1);

  const reopened = await openAvaliacao(page);
  await expectTargetRubricValues(reopened.frameLocator, overrideAlunoId, scenario.mapping, preservedBeforeCurrentCopy);
  if (scenario.mapping.componentMappings.length) {
    for (const componentMapping of scenario.mapping.componentMappings) {
      await expect(
        reopened.frameLocator.locator(componentSelector(copiedAlunoId, scenario.mapping.targetRubricId, componentMapping.targetId))
      ).toHaveValue(seededSourceValues.expectedValuesByTargetId[componentMapping.targetId]);
    }
  } else {
    await expect(reopened.frameLocator.locator(studentRubricSelector(copiedAlunoId, scenario.mapping.targetRubricId))).toHaveValue('4.5');
  }
});

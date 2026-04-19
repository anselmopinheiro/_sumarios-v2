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

function studentRubricSelector(alunoId, rubricaId) {
  return `.js-student-score[data-aluno-id="${alunoId}"][data-rubrica-id="${rubricaId}"]`;
}

function componentSelector(alunoId, rubricaId, componentId) {
  return `.js-component-score[data-aluno-id="${alunoId}"][data-rubrica-id="${rubricaId}"][data-component-id="${componentId}"]`;
}

function numericValuePattern(expectedValue) {
  const escapedValue = String(expectedValue).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
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
      const name = normalizeKey(component?.nome);
      return name ? `name:${name}` : '';
    };

    const buildPlan = (sourceDomain, targetDomain) => {
      const sourceRubrics = Array.isArray(sourceDomain?.rubricas) ? sourceDomain.rubricas : [];
      const targetRubrics = Array.isArray(targetDomain?.rubricas) ? targetDomain.rubricas : [];
      const sourceMap = uniqueMap(sourceRubrics, rubricKey);
      const targetMap = uniqueMap(targetRubrics, rubricKey);
      const mappings = [];
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
        if (!sourceComponents.length || !targetComponents.length) return;
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
          return;
        }
        mappings.push({
          sourceRubricId: String(sourceRubric.id),
          targetRubricId: String(targetRubric.id),
          componentMappings,
        });
      });
      return mappings;
    };

    for (const sourceDomain of payload) {
      for (const targetDomain of payload) {
        if (!sourceDomain?.client_id || !targetDomain?.client_id || sourceDomain.client_id === targetDomain.client_id) continue;
        const mappings = buildPlan(sourceDomain, targetDomain);
        const mapping = mappings.find((candidate) => {
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
          studentIds: candidateRows.slice(0, studentCount).map((row) => String(row.dataset.alunoId)),
        };
      }
    }
    return null;
  }, { studentCount });
}

async function resolveFillScenario(frame) {
  return frame.evaluate(() => {
    const table = document.getElementById('avaliacao-objeto-table');
    const baseFillValue = Number(table?.dataset.baseFillValue || 3) || 3;
    const allSimpleInputs = Array.from(document.querySelectorAll('.js-student-score:not([readonly]):not(:disabled)'));
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

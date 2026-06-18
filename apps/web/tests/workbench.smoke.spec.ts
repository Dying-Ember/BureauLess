import { expect, test } from '@playwright/test';

test('renders DAG workbench and node inspector', async ({ page }) => {
  await page.goto('/');

  await expect(page.getByText('agents-swarm')).toBeVisible();
  await expect(page.getByText('Baseline Inventory').first()).toBeVisible();
  await expect(page.getByText('Worker Stop Lifecycle').first()).toBeVisible();

  await page.getByRole('button', { name: /worker stop lifecycle/i }).click();

  await expect(page.getByRole('heading', { name: 'worker-stop-lifecycle' })).toBeVisible();
  await expect(page.getByText('risk: high')).toBeVisible();
  await expect(page.getByText('gpt-5').first()).toBeVisible();
  await expect(page.getByText('human_review').first()).toBeVisible();
});

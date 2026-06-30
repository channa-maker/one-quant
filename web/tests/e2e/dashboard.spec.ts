import { test, expect } from '@playwright/test';

test.describe('总览大盘', () => {
  test('加载总览页面', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('text=总览')).toBeVisible();
  });

  test('显示总资产卡片', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('[data-testid="total-assets"]')).toBeVisible();
  });

  test('显示今日盈亏', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('[data-testid="daily-pnl"]')).toBeVisible();
  });

  test('显示风控状态', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('[data-testid="risk-status"]')).toBeVisible();
  });
});

test.describe('交易终端', () => {
  test('加载K线图', async ({ page }) => {
    await page.goto('/trading');
    await expect(page.locator('[data-testid="kline-chart"]')).toBeVisible();
  });

  test('显示下单面板', async ({ page }) => {
    await page.goto('/trading');
    await expect(page.locator('[data-testid="order-panel"]')).toBeVisible();
  });

  test('显示持仓列表', async ({ page }) => {
    await page.goto('/trading');
    await expect(page.locator('[data-testid="positions-list"]')).toBeVisible();
  });
});

test.describe('策略管理', () => {
  test('加载策略列表', async ({ page }) => {
    await page.goto('/strategies');
    await expect(page.locator('[data-testid="strategy-list"]')).toBeVisible();
  });
});

test.describe('风控中心', () => {
  test('显示四层风控状态', async ({ page }) => {
    await page.goto('/risk');
    await expect(page.locator('[data-testid="risk-l1"]')).toBeVisible();
    await expect(page.locator('[data-testid="risk-l2"]')).toBeVisible();
    await expect(page.locator('[data-testid="risk-l3"]')).toBeVisible();
    await expect(page.locator('[data-testid="risk-l4"]')).toBeVisible();
  });
});

test.describe('鉴权', () => {
  test('未登录跳转登录页', async ({ page }) => {
    await page.goto('/trading');
    // 应重定向到登录页或显示登录提示
    await expect(page.locator('text=登录')).toBeVisible();
  });
});

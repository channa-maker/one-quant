import { test, expect } from '@playwright/test';

// 未登录:一律重定向到登录页
test.describe('登录守卫', () => {
  test('未登录访问首页跳转登录页', async ({ page }) => {
    await page.goto('/');
    await expect(page).toHaveURL(/\/login/);
    await expect(page.getByText('ONE 量化')).toBeVisible();
    await expect(page.getByPlaceholder('用户名')).toBeVisible();
    await expect(page.getByPlaceholder('密码')).toBeVisible();
  });
});

// 注入 token 后可进入主布局(不依赖后端)
test.describe('主布局(已登录)', () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => {
      localStorage.setItem('one_quant_token', 'e2e-fake-token');
    });
  });

  test('侧边栏中文菜单齐全', async ({ page }) => {
    await page.goto('/');
    for (const label of ['总览大盘', '交易终端', '盯盘工作站', '策略管理', 'AI 研报', '选股选币', '期权中心', '持仓账户', '风控中心', '审计日志', '系统监控']) {
      await expect(page.getByRole('menuitem', { name: label })).toBeVisible();
    }
  });

  test('交易终端渲染 K 线画布', async ({ page }) => {
    await page.goto('/trade');
    await expect(page.locator('canvas').first()).toBeVisible({ timeout: 10000 });
  });

  test('盯盘工作站可达', async ({ page }) => {
    await page.goto('/workstation');
    await expect(page.getByRole('menuitem', { name: '盯盘工作站' })).toBeVisible();
  });

  test('选股选币展示候选池', async ({ page }) => {
    await page.goto('/screener');
    await expect(page.getByText('AI 选股选币')).toBeVisible();
    await expect(page.getByText('今日候选池', { exact: false })).toBeVisible();
  });

  test('审计日志可检索', async ({ page }) => {
    await page.goto('/audit');
    await expect(page.getByText('审计日志').first()).toBeVisible();
  });
});

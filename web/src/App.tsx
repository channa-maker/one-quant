import React, { Suspense, lazy } from 'react'
import { Routes, Route, useNavigate, useLocation } from 'react-router-dom'
import { Layout, Menu, Badge, Typography, Spin, ConfigProvider, theme, Space, Tooltip } from 'antd'
import {
  DashboardOutlined,
  LineChartOutlined,
  FundOutlined,
  SafetyOutlined,
  RobotOutlined,
  WalletOutlined,
  CloudServerOutlined,
} from '@ant-design/icons'
import { useWebSocket } from '@/hooks/useWebSocket'
import { useAppStore } from '@/store'

const { Header, Sider, Content } = Layout
const { Title, Text } = Typography

/** 懒加载页面 */
const Dashboard = lazy(() => import('@/pages/Dashboard'))
const TradingTerminal = lazy(() => import('@/pages/TradingTerminal'))
const StrategyManagement = lazy(() => import('@/pages/StrategyManagement'))
const AIResearch = lazy(() => import('@/pages/AIResearch'))
const RiskCenter = lazy(() => import('@/pages/RiskCenter'))
const Portfolio = lazy(() => import('@/pages/Portfolio'))
const SystemMonitor = lazy(() => import('@/pages/SystemMonitor'))

/** 导航菜单 */
const menuItems = [
  { key: '/', icon: <DashboardOutlined />, label: '总览大盘' },
  { key: '/trade', icon: <LineChartOutlined />, label: '交易终端' },
  { key: '/strategies', icon: <FundOutlined />, label: '策略管理' },
  { key: '/ai', icon: <RobotOutlined />, label: 'AI 研报' },
  { key: '/portfolio', icon: <WalletOutlined />, label: '持仓账户' },
  { key: '/risk', icon: <SafetyOutlined />, label: '风控中心' },
  { key: '/monitor', icon: <CloudServerOutlined />, label: '系统监控' },
]

/** 加载占位 */
const PageLoading = () => (
  <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '50vh' }}>
    <Spin size="large" tip="加载中..." />
  </div>
)

export default function App() {
  useWebSocket('market')
  const wsConnected = useAppStore((s) => s.wsConnected)
  const navigate = useNavigate()
  const location = useLocation()

  return (
    <ConfigProvider
      theme={{
        algorithm: theme.darkAlgorithm,
        token: {
          colorPrimary: '#1677ff',
          borderRadius: 6,
          fontSize: 13,
        },
        components: {
          Layout: {
            siderBg: '#141414',
            headerBg: '#1a1a1a',
            bodyBg: '#0d0d0d',
          },
          Menu: {
            darkItemBg: '#141414',
            darkSubMenuItemBg: '#141414',
          },
          Card: {
            colorBgContainer: '#1a1a1a',
          },
          Table: {
            colorBgContainer: '#1a1a1a',
          },
        },
      }}
    >
      <Layout style={{ minHeight: '100vh' }}>
        <Sider
          theme="dark"
          width={200}
          style={{
            overflow: 'auto',
            height: '100vh',
            position: 'fixed',
            left: 0,
            top: 0,
            bottom: 0,
            borderRight: '1px solid #303030',
          }}
        >
          {/* Logo */}
          <div
            style={{
              padding: '16px 20px',
              display: 'flex',
              alignItems: 'center',
              gap: 10,
              borderBottom: '1px solid #303030',
            }}
          >
            <div
              style={{
                width: 32,
                height: 32,
                borderRadius: 8,
                background: 'linear-gradient(135deg, #1677ff, #4096ff)',
                display: 'flex',
                justifyContent: 'center',
                alignItems: 'center',
                fontWeight: 'bold',
                fontSize: 16,
                color: '#fff',
              }}
            >
              O
            </div>
            <div>
              <div style={{ color: '#fff', fontSize: 16, fontWeight: 'bold', lineHeight: 1.2 }}>
                ONE 量化
              </div>
              <div style={{ color: '#8c8c8c', fontSize: 11 }}>机构级智能量化交易系统</div>
            </div>
          </div>

          <Menu
            theme="dark"
            mode="inline"
            selectedKeys={[location.pathname]}
            items={menuItems}
            onClick={({ key }) => navigate(key)}
            style={{ borderRight: 0 }}
          />

          {/* 底部状态 */}
          <div
            style={{
              position: 'absolute',
              bottom: 0,
              left: 0,
              right: 0,
              padding: '12px 16px',
              borderTop: '1px solid #303030',
            }}
          >
            <Badge
              status={wsConnected ? 'success' : 'error'}
              text={
                <Text style={{ color: '#8c8c8c', fontSize: 12 }}>
                  {wsConnected ? '行情已连接' : '行情断开'}
                </Text>
              }
            />
          </div>
        </Sider>

        <Layout style={{ marginLeft: 200 }}>
          <Header
            style={{
              padding: '0 24px',
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              borderBottom: '1px solid #303030',
              position: 'sticky',
              top: 0,
              zIndex: 10,
            }}
          >
            <Title level={5} style={{ margin: 0, color: '#ffffffd9' }}>
              ONE量化 · 机构级智能量化交易系统
            </Title>
            <Space size={16}>
              <Tooltip title={wsConnected ? 'WebSocket 已连接' : 'WebSocket 断开'}>
                <Badge status={wsConnected ? 'success' : 'error'} />
              </Tooltip>
              <Text type="secondary" style={{ fontSize: 12 }}>
                {new Date().toLocaleString('zh-CN')}
              </Text>
            </Space>
          </Header>

          <Content style={{ minHeight: 'calc(100vh - 64px)', background: '#0d0d0d' }}>
            <Suspense fallback={<PageLoading />}>
              <Routes>
                <Route path="/" element={<Dashboard />} />
                <Route path="/trade" element={<TradingTerminal />} />
                <Route path="/strategies" element={<StrategyManagement />} />
                <Route path="/ai" element={<AIResearch />} />
                <Route path="/portfolio" element={<Portfolio />} />
                <Route path="/risk" element={<RiskCenter />} />
                <Route path="/monitor" element={<SystemMonitor />} />
              </Routes>
            </Suspense>
          </Content>
        </Layout>
      </Layout>
    </ConfigProvider>
  )
}

import { Suspense, lazy } from 'react'
import { Routes, Route, useNavigate, useLocation, Navigate } from 'react-router-dom'
import {
  Layout, Menu, Badge, Typography, Spin, ConfigProvider, theme, Space, Tooltip, Button,
} from 'antd'
import zhCN from 'antd/locale/zh_CN'
import {
  DashboardOutlined, LineChartOutlined, FundOutlined, SafetyOutlined,
  RobotOutlined, WalletOutlined, CloudServerOutlined, DesktopOutlined,
  ExperimentOutlined, FileSearchOutlined, LogoutOutlined,
} from '@ant-design/icons'
import { useWebSocket } from '@/hooks/useWebSocket'
import { useAppStore } from '@/store'
import { getToken, clearToken } from '@/utils/api'

const { Header, Sider, Content } = Layout
const { Title, Text } = Typography

/** 懒加载页面 */
const Dashboard = lazy(() => import('@/pages/Dashboard'))
const TradingTerminal = lazy(() => import('@/pages/TradingTerminal'))
const Workstation = lazy(() => import('@/pages/Workstation'))
const StrategyManagement = lazy(() => import('@/pages/StrategyManagement'))
const AIResearch = lazy(() => import('@/pages/AIResearch'))
const Screener = lazy(() => import('@/pages/Screener'))
const OptionsCenter = lazy(() => import('@/pages/OptionsCenter'))
const RiskCenter = lazy(() => import('@/pages/RiskCenter'))
const Portfolio = lazy(() => import('@/pages/Portfolio'))
const AuditLog = lazy(() => import('@/pages/AuditLog'))
const SystemMonitor = lazy(() => import('@/pages/SystemMonitor'))
const Login = lazy(() => import('@/pages/Login'))

/** 导航菜单(全中文) */
const menuItems = [
  { key: '/', icon: <DashboardOutlined />, label: '总览大盘' },
  { key: '/trade', icon: <LineChartOutlined />, label: '交易终端' },
  { key: '/workstation', icon: <DesktopOutlined />, label: '盯盘工作站' },
  { key: '/strategies', icon: <FundOutlined />, label: '策略管理' },
  { key: '/ai', icon: <RobotOutlined />, label: 'AI 研报' },
  { key: '/screener', icon: <ExperimentOutlined />, label: '选股选币' },
  { key: '/options', icon: <FundOutlined />, label: '期权中心' },
  { key: '/portfolio', icon: <WalletOutlined />, label: '持仓账户' },
  { key: '/risk', icon: <SafetyOutlined />, label: '风控中心' },
  { key: '/audit', icon: <FileSearchOutlined />, label: '审计日志' },
  { key: '/monitor', icon: <CloudServerOutlined />, label: '系统监控' },
]

/** 加载占位 */
const PageLoading = () => (
  <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '50vh' }}>
    <Spin size="large" tip="加载中..." />
  </div>
)

/** 暗色主题(交易场景) */
const darkTheme = {
  algorithm: theme.darkAlgorithm,
  token: { colorPrimary: '#1677ff', borderRadius: 6, fontSize: 13 },
  components: {
    Layout: { siderBg: '#141414', headerBg: '#1a1a1a', bodyBg: '#0d0d0d' },
    Menu: { darkItemBg: '#141414', darkSubMenuItemBg: '#141414' },
    Card: { colorBgContainer: '#1a1a1a' },
    Table: { colorBgContainer: '#1a1a1a' },
  },
}

/** 主布局(需登录) */
function MainLayout() {
  useWebSocket('market')
  const wsConnected = useAppStore((s) => s.wsConnected)
  const auth = useAppStore((s) => s.auth)
  const setAuth = useAppStore((s) => s.setAuth)
  const navigate = useNavigate()
  const location = useLocation()

  const onLogout = () => {
    clearToken()
    setAuth(null)
    navigate('/login')
  }

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Sider
        theme="dark"
        width={200}
        style={{
          overflow: 'auto', height: '100vh', position: 'fixed',
          left: 0, top: 0, bottom: 0, borderRight: '1px solid #303030',
        }}
      >
        <div style={{ padding: '16px 20px', display: 'flex', alignItems: 'center', gap: 10, borderBottom: '1px solid #303030' }}>
          <div style={{
            width: 32, height: 32, borderRadius: 8,
            background: 'linear-gradient(135deg, #1677ff, #4096ff)',
            display: 'flex', justifyContent: 'center', alignItems: 'center',
            fontWeight: 'bold', fontSize: 16, color: '#fff',
          }}>O</div>
          <div>
            <div style={{ color: '#fff', fontSize: 16, fontWeight: 'bold', lineHeight: 1.2 }}>ONE 量化</div>
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

        <div style={{ position: 'absolute', bottom: 0, left: 0, right: 0, padding: '12px 16px', borderTop: '1px solid #303030' }}>
          <Badge
            status={wsConnected ? 'success' : 'error'}
            text={<Text style={{ color: '#8c8c8c', fontSize: 12 }}>{wsConnected ? '行情已连接' : '行情断开'}</Text>}
          />
        </div>
      </Sider>

      <Layout style={{ marginLeft: 200 }}>
        <Header style={{
          padding: '0 24px', display: 'flex', justifyContent: 'space-between', alignItems: 'center',
          borderBottom: '1px solid #303030', position: 'sticky', top: 0, zIndex: 10,
        }}>
          <Title level={5} style={{ margin: 0, color: '#ffffffd9' }}>
            ONE量化 · 机构级智能量化交易系统
          </Title>
          <Space size={16}>
            <Tooltip title={wsConnected ? 'WebSocket 已连接' : 'WebSocket 断开'}>
              <Badge status={wsConnected ? 'success' : 'error'} />
            </Tooltip>
            {auth && <Text type="secondary" style={{ fontSize: 12 }}>{auth.username}({auth.role})</Text>}
            <Tooltip title="退出登录">
              <Button type="text" size="small" icon={<LogoutOutlined />} onClick={onLogout} />
            </Tooltip>
          </Space>
        </Header>

        <Content style={{ minHeight: 'calc(100vh - 64px)', background: '#0d0d0d' }}>
          <Suspense fallback={<PageLoading />}>
            <Routes>
              <Route path="/" element={<Dashboard />} />
              <Route path="/trade" element={<TradingTerminal />} />
              <Route path="/workstation" element={<Workstation />} />
              <Route path="/strategies" element={<StrategyManagement />} />
              <Route path="/ai" element={<AIResearch />} />
              <Route path="/screener" element={<Screener />} />
              <Route path="/options" element={<OptionsCenter />} />
              <Route path="/portfolio" element={<Portfolio />} />
              <Route path="/risk" element={<RiskCenter />} />
              <Route path="/audit" element={<AuditLog />} />
              <Route path="/monitor" element={<SystemMonitor />} />
            </Routes>
          </Suspense>
        </Content>
      </Layout>
    </Layout>
  )
}

/** 路由守卫:无 token 一律去登录页 */
function RequireAuth({ children }: { children: JSX.Element }) {
  if (!getToken()) return <Navigate to="/login" replace />
  return children
}

export default function App() {
  return (
    <ConfigProvider locale={zhCN} theme={darkTheme}>
      <Suspense fallback={<PageLoading />}>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/*" element={<RequireAuth><MainLayout /></RequireAuth>} />
        </Routes>
      </Suspense>
    </ConfigProvider>
  )
}

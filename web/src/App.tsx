import { Routes, Route } from 'react-router-dom'
import { Layout, Menu, Badge, Typography } from 'antd'
import {
  DashboardOutlined,
  LineChartOutlined,
  SafetyOutlined,
  FundOutlined,
  SettingOutlined,
} from '@ant-design/icons'
import { useWebSocket } from '@/hooks/useWebSocket'
import { useAppStore } from '@/store'

const { Header, Sider, Content } = Layout
const { Title } = Typography

const menuItems = [
  { key: '/', icon: <DashboardOutlined />, label: '总览大盘' },
  { key: '/trade', icon: <LineChartOutlined />, label: '交易终端' },
  { key: '/strategies', icon: <FundOutlined />, label: '策略管理' },
  { key: '/risk', icon: <SafetyOutlined />, label: '风控中心' },
  { key: '/monitor', icon: <SettingOutlined />, label: '系统监控' },
]

function Dashboard() {
  const tickers = useAppStore((s) => s.tickers)
  const positions = useAppStore((s) => s.positions)
  const signals = useAppStore((s) => s.signals)

  return (
    <div style={{ padding: 24 }}>
      <Title level={3}>📊 总览大盘</Title>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 16 }}>
        <div style={{ background: '#f0f2f5', padding: 16, borderRadius: 8 }}>
          <div>行情数量</div>
          <div style={{ fontSize: 24, fontWeight: 'bold' }}>{Object.keys(tickers).length}</div>
        </div>
        <div style={{ background: '#f0f2f5', padding: 16, borderRadius: 8 }}>
          <div>持仓数量</div>
          <div style={{ fontSize: 24, fontWeight: 'bold' }}>{positions.length}</div>
        </div>
        <div style={{ background: '#f0f2f5', padding: 16, borderRadius: 8 }}>
          <div>今日信号</div>
          <div style={{ fontSize: 24, fontWeight: 'bold' }}>{signals.length}</div>
        </div>
      </div>
    </div>
  )
}

function TradeTerminal() {
  return <div style={{ padding: 24 }}><Title level={3}>💹 交易终端</Title><p>开发中...</p></div>
}
function StrategyPage() {
  return <div style={{ padding: 24 }}><Title level={3}>🧠 策略管理</Title><p>开发中...</p></div>
}
function RiskCenter() {
  return <div style={{ padding: 24 }}><Title level={3}>🛡️ 风控中心</Title><p>开发中...</p></div>
}
function MonitorPage() {
  return <div style={{ padding: 24 }}><Title level={3}>⚙️ 系统监控</Title><p>开发中...</p></div>
}

export default function App() {
  useWebSocket('market')
  const wsConnected = useAppStore((s) => s.wsConnected)

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Sider theme="dark">
        <div style={{ padding: 16, color: 'white', fontSize: 18, fontWeight: 'bold' }}>
          ONE量化
        </div>
        <Menu
          theme="dark"
          defaultSelectedKeys={['/']}
          items={menuItems}
          onClick={({ key }) => window.location.hash = key}
        />
      </Sider>
      <Layout>
        <Header style={{ background: '#fff', padding: '0 24px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <Title level={4} style={{ margin: 0 }}>ONE量化 · 机构级智能量化交易系统</Title>
          <Badge status={wsConnected ? 'success' : 'error'} text={wsConnected ? '已连接' : '未连接'} />
        </Header>
        <Content>
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/trade" element={<TradeTerminal />} />
            <Route path="/strategies" element={<StrategyPage />} />
            <Route path="/risk" element={<RiskCenter />} />
            <Route path="/monitor" element={<MonitorPage />} />
          </Routes>
        </Content>
      </Layout>
    </Layout>
  )
}

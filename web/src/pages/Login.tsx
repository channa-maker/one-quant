/**
 * 登录页 — JWT 认证入口。
 */
import { useState } from 'react'
import { Card, Form, Input, Button, Typography, message, Alert } from 'antd'
import { UserOutlined, LockOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { login, setToken } from '@/utils/api'
import { useAppStore } from '@/store'

const { Title, Text } = Typography

export default function Login() {
  const [loading, setLoading] = useState(false)
  const navigate = useNavigate()
  const setAuth = useAppStore((s) => s.setAuth)

  const onFinish = async (values: { username: string; password: string }) => {
    setLoading(true)
    try {
      const result = await login(values.username, values.password)
      setToken(result.access_token)
      setAuth({ username: result.username, role: result.role })
      message.success('登录成功')
      navigate('/')
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { error?: string } } })?.response?.data?.error ||
        '登录失败,请检查网络或联系管理员'
      message.error(detail)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div
      style={{
        minHeight: '100vh',
        display: 'flex',
        justifyContent: 'center',
        alignItems: 'center',
        background: '#0d0d0d',
      }}
    >
      <Card style={{ width: 380, background: '#1a1a1a', border: '1px solid #303030' }}>
        <div style={{ textAlign: 'center', marginBottom: 24 }}>
          <div
            style={{
              width: 48,
              height: 48,
              margin: '0 auto 12px',
              borderRadius: 12,
              background: 'linear-gradient(135deg, #1677ff, #4096ff)',
              display: 'flex',
              justifyContent: 'center',
              alignItems: 'center',
              fontWeight: 'bold',
              fontSize: 24,
              color: '#fff',
            }}
          >
            O
          </div>
          <Title level={4} style={{ margin: 0 }}>
            ONE 量化
          </Title>
          <Text type="secondary">机构级智能量化交易系统</Text>
        </div>

        <Form name="login" onFinish={onFinish} autoComplete="off" size="large">
          <Form.Item name="username" rules={[{ required: true, message: '请输入用户名' }]}>
            <Input prefix={<UserOutlined />} placeholder="用户名" />
          </Form.Item>
          <Form.Item name="password" rules={[{ required: true, message: '请输入密码' }]}>
            <Input.Password prefix={<LockOutlined />} placeholder="密码" />
          </Form.Item>
          <Form.Item>
            <Button type="primary" htmlType="submit" block loading={loading}>
              登 录
            </Button>
          </Form.Item>
        </Form>

        <Alert
          type="info"
          showIcon
          message="服务端需配置 ONE_ADMIN_PASSWORD 环境变量后方可登录"
          style={{ fontSize: 12 }}
        />
      </Card>
    </div>
  )
}

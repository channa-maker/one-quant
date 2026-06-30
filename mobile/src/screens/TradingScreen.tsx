/**
 * ONE量化 · 移动端交易
 * 标的选择 · 价格/数量输入 · 买入/卖出 · 二次确认弹窗
 */
import React, { useState, useCallback } from 'react';
import {
  View,
  Text,
  StyleSheet,
  TextInput,
  TouchableOpacity,
  ScrollView,
  Alert,
  Modal,
  ActivityIndicator,
} from 'react-native';
import { useMutation } from '@tanstack/react-query';

// ── 类型 ──────────────────────────────────────────────────
type TradeSide = 'buy' | 'sell';
type OrderType = 'limit' | 'market';

interface SymbolItem {
  symbol: string;
  name: string;
  price: number;
  change: number;
}

// ── 热门标的 ──────────────────────────────────────────────
const HOT_SYMBOLS: SymbolItem[] = [
  { symbol: '600519', name: '贵州茅台', price: 1680.0, change: 1.67 },
  { symbol: '300750', name: '宁德时代', price: 198.5, change: 3.21 },
  { symbol: '601318', name: '中国平安', price: 48.2, change: -1.23 },
  { symbol: 'BTCUSDT', name: '比特币', price: 68500, change: 2.45 },
  { symbol: 'ETHUSDT', name: '以太坊', price: 3580, change: 1.88 },
  { symbol: '000858', name: '五粮液', price: 152.5, change: 0.53 },
  { symbol: '09988', name: '阿里巴巴-W', price: 82.3, change: 0.98 },
  { symbol: 'NVDA', name: '英伟达', price: 125.6, change: 4.12 },
];

// ── 格式化 ────────────────────────────────────────────────
function formatPrice(n: number): string {
  return n.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function pnlColor(n: number): string {
  if (n > 0) return '#FF5252';
  if (n < 0) return '#4CAF50';
  return '#888';
}

// ── 主组件 ────────────────────────────────────────────────
export default function TradingScreen() {
  const [selectedSymbol, setSelectedSymbol] = useState<SymbolItem | null>(null);
  const [side, setSide] = useState<TradeSide>('buy');
  const [orderType, setOrderType] = useState<OrderType>('limit');
  const [price, setPrice] = useState('');
  const [quantity, setQuantity] = useState('');
  const [showSymbolPicker, setShowSymbolPicker] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);

  // 提交订单
  const submitMutation = useMutation({
    mutationFn: async (order: any) => {
      // TODO: 替换为真实 API
      await new Promise((r) => setTimeout(r, 1000));
      return { success: true, orderId: 'ORD-' + Date.now() };
    },
    onSuccess: (data) => {
      Alert.alert('下单成功', `委托已提交\n订单号：${data.orderId}`, [{ text: '确定' }]);
      setPrice('');
      setQuantity('');
    },
    onError: (error: any) => {
      Alert.alert('下单失败', error.message || '请检查参数后重试', [{ text: '确定' }]);
    },
  });

  // 选择标的
  const handleSelectSymbol = useCallback((item: SymbolItem) => {
    setSelectedSymbol(item);
    setPrice(formatPrice(item.price));
    setShowSymbolPicker(false);
  }, []);

  // 验证并弹出确认
  const handleSubmit = useCallback(() => {
    if (!selectedSymbol) {
      Alert.alert('提示', '请先选择标的', [{ text: '确定' }]);
      return;
    }
    if (orderType === 'limit' && (!price || parseFloat(price) <= 0)) {
      Alert.alert('提示', '请输入有效价格', [{ text: '确定' }]);
      return;
    }
    if (!quantity || parseInt(quantity) <= 0) {
      Alert.alert('提示', '请输入有效数量', [{ text: '确定' }]);
      return;
    }
    setShowConfirm(true);
  }, [selectedSymbol, price, quantity, orderType]);

  // 确认下单
  const handleConfirm = useCallback(() => {
    setShowConfirm(false);
    submitMutation.mutate({
      symbol: selectedSymbol!.symbol,
      side,
      orderType,
      price: orderType === 'limit' ? parseFloat(price) : null,
      quantity: parseInt(quantity),
    });
  }, [selectedSymbol, side, orderType, price, quantity, submitMutation]);

  const totalAmount = selectedSymbol && price && quantity
    ? parseFloat(price) * parseInt(quantity)
    : 0;

  return (
    <View style={styles.container}>
      <ScrollView contentContainerStyle={styles.scrollContent}>
        {/* 标的选择 */}
        <Text style={styles.label}>交易标的</Text>
        <TouchableOpacity
          style={styles.symbolSelector}
          onPress={() => setShowSymbolPicker(true)}
        >
          {selectedSymbol ? (
            <View style={styles.selectedSymbolRow}>
              <View>
                <Text style={styles.selectedSymbolName}>{selectedSymbol.name}</Text>
                <Text style={styles.selectedSymbolCode}>{selectedSymbol.symbol}</Text>
              </View>
              <Text style={styles.selectedSymbolPrice}>
                ¥{formatPrice(selectedSymbol.price)}
              </Text>
            </View>
          ) : (
            <Text style={styles.placeholder}>点击选择标的</Text>
          )}
        </TouchableOpacity>

        {/* 买入/卖出 */}
        <Text style={styles.label}>交易方向</Text>
        <View style={styles.sideRow}>
          <TouchableOpacity
            style={[styles.sideButton, side === 'buy' && styles.sideButtonBuyActive]}
            onPress={() => setSide('buy')}
          >
            <Text style={[styles.sideButtonText, side === 'buy' && styles.sideButtonTextActive]}>
              买入
            </Text>
          </TouchableOpacity>
          <TouchableOpacity
            style={[styles.sideButton, side === 'sell' && styles.sideButtonSellActive]}
            onPress={() => setSide('sell')}
          >
            <Text style={[styles.sideButtonText, side === 'sell' && styles.sideButtonTextActive]}>
              卖出
            </Text>
          </TouchableOpacity>
        </View>

        {/* 委托类型 */}
        <Text style={styles.label}>委托类型</Text>
        <View style={styles.typeRow}>
          <TouchableOpacity
            style={[styles.typeButton, orderType === 'limit' && styles.typeButtonActive]}
            onPress={() => setOrderType('limit')}
          >
            <Text style={[styles.typeButtonText, orderType === 'limit' && styles.typeButtonTextActive]}>
              限价
            </Text>
          </TouchableOpacity>
          <TouchableOpacity
            style={[styles.typeButton, orderType === 'market' && styles.typeButtonActive]}
            onPress={() => setOrderType('market')}
          >
            <Text style={[styles.typeButtonText, orderType === 'market' && styles.typeButtonTextActive]}>
              市价
            </Text>
          </TouchableOpacity>
        </View>

        {/* 价格输入 */}
        {orderType === 'limit' && (
          <>
            <Text style={styles.label}>委托价格</Text>
            <View style={styles.inputRow}>
              <TouchableOpacity
                style={styles.adjustButton}
                onPress={() => {
                  const p = parseFloat(price) || 0;
                  setPrice(formatPrice(Math.max(0, p - (selectedSymbol?.price ?? 1) * 0.01)));
                }}
              >
                <Text style={styles.adjustButtonText}>−</Text>
              </TouchableOpacity>
              <TextInput
                style={styles.input}
                value={price}
                onChangeText={setPrice}
                keyboardType="decimal-pad"
                placeholder="输入价格"
                placeholderTextColor="#555"
              />
              <TouchableOpacity
                style={styles.adjustButton}
                onPress={() => {
                  const p = parseFloat(price) || 0;
                  setPrice(formatPrice(p + (selectedSymbol?.price ?? 1) * 0.01));
                }}
              >
                <Text style={styles.adjustButtonText}>+</Text>
              </TouchableOpacity>
            </View>
          </>
        )}

        {/* 数量输入 */}
        <Text style={styles.label}>委托数量</Text>
        <View style={styles.inputRow}>
          <TouchableOpacity
            style={styles.adjustButton}
            onPress={() => {
              const q = parseInt(quantity) || 0;
              setQuantity(String(Math.max(0, q - 100)));
            }}
          >
            <Text style={styles.adjustButtonText}>−</Text>
          </TouchableOpacity>
          <TextInput
            style={styles.input}
            value={quantity}
            onChangeText={setQuantity}
            keyboardType="number-pad"
            placeholder="输入数量"
            placeholderTextColor="#555"
          />
          <TouchableOpacity
            style={styles.adjustButton}
            onPress={() => {
              const q = parseInt(quantity) || 0;
              setQuantity(String(q + 100));
            }}
          >
            <Text style={styles.adjustButtonText}>+</Text>
          </TouchableOpacity>
        </View>

        {/* 快捷数量 */}
        <View style={styles.quickQtyRow}>
          {[100, 500, 1000, 5000].map((q) => (
            <TouchableOpacity
              key={q}
              style={styles.quickQtyButton}
              onPress={() => setQuantity(String(q))}
            >
              <Text style={styles.quickQtyText}>{q}股</Text>
            </TouchableOpacity>
          ))}
        </View>

        {/* 预估金额 */}
        {totalAmount > 0 && (
          <View style={styles.summaryCard}>
            <View style={styles.summaryRow}>
              <Text style={styles.summaryLabel}>预估金额</Text>
              <Text style={styles.summaryValue}>¥{totalAmount.toLocaleString('zh-CN')}</Text>
            </View>
          </View>
        )}

        {/* 提交按钮 */}
        <TouchableOpacity
          style={[
            styles.submitButton,
            side === 'buy' ? styles.submitButtonBuy : styles.submitButtonSell,
            submitMutation.isPending && styles.submitButtonDisabled,
          ]}
          onPress={handleSubmit}
          disabled={submitMutation.isPending}
        >
          {submitMutation.isPending ? (
            <ActivityIndicator color="#FFF" />
          ) : (
            <Text style={styles.submitButtonText}>
              {side === 'buy' ? '买入' : '卖出'} {selectedSymbol?.name ?? ''}
            </Text>
          )}
        </TouchableOpacity>

        {/* 热门标的 */}
        <Text style={[styles.label, { marginTop: 24 }]}>热门标的</Text>
        {HOT_SYMBOLS.map((item) => (
          <TouchableOpacity
            key={item.symbol}
            style={styles.hotSymbolRow}
            onPress={() => handleSelectSymbol(item)}
          >
            <View style={styles.hotSymbolInfo}>
              <Text style={styles.hotSymbolName}>{item.name}</Text>
              <Text style={styles.hotSymbolCode}>{item.symbol}</Text>
            </View>
            <Text style={styles.hotSymbolPrice}>¥{formatPrice(item.price)}</Text>
            <Text style={[styles.hotSymbolChange, { color: pnlColor(item.change) }]}>
              {item.change >= 0 ? '+' : ''}{item.change.toFixed(2)}%
            </Text>
          </TouchableOpacity>
        ))}

        <View style={{ height: 40 }} />
      </ScrollView>

      {/* 标的选择弹窗 */}
      <Modal visible={showSymbolPicker} animationType="slide" transparent>
        <View style={styles.modalOverlay}>
          <View style={styles.modalContent}>
            <View style={styles.modalHeader}>
              <Text style={styles.modalTitle}>选择标的</Text>
              <TouchableOpacity onPress={() => setShowSymbolPicker(false)}>
                <Text style={styles.modalClose}>✕</Text>
              </TouchableOpacity>
            </View>
            <ScrollView>
              {HOT_SYMBOLS.map((item) => (
                <TouchableOpacity
                  key={item.symbol}
                  style={styles.modalSymbolRow}
                  onPress={() => handleSelectSymbol(item)}
                >
                  <View>
                    <Text style={styles.modalSymbolName}>{item.name}</Text>
                    <Text style={styles.modalSymbolCode}>{item.symbol}</Text>
                  </View>
                  <View style={{ alignItems: 'flex-end' }}>
                    <Text style={styles.modalSymbolPrice}>¥{formatPrice(item.price)}</Text>
                    <Text style={[styles.modalSymbolChange, { color: pnlColor(item.change) }]}>
                      {item.change >= 0 ? '+' : ''}{item.change.toFixed(2)}%
                    </Text>
                  </View>
                </TouchableOpacity>
              ))}
            </ScrollView>
          </View>
        </View>
      </Modal>

      {/* 二次确认弹窗 */}
      <Modal visible={showConfirm} animationType="fade" transparent>
        <View style={styles.modalOverlay}>
          <View style={styles.confirmCard}>
            <Text style={styles.confirmTitle}>⚠️ 确认下单</Text>
            <View style={styles.confirmDivider} />

            <View style={styles.confirmRow}>
              <Text style={styles.confirmLabel}>标的</Text>
              <Text style={styles.confirmValue}>{selectedSymbol?.name}（{selectedSymbol?.symbol}）</Text>
            </View>
            <View style={styles.confirmRow}>
              <Text style={styles.confirmLabel}>方向</Text>
              <Text style={[styles.confirmValue, { color: side === 'buy' ? '#FF5252' : '#4CAF50' }]}>
                {side === 'buy' ? '买入' : '卖出'}
              </Text>
            </View>
            <View style={styles.confirmRow}>
              <Text style={styles.confirmLabel}>类型</Text>
              <Text style={styles.confirmValue}>{orderType === 'limit' ? '限价' : '市价'}</Text>
            </View>
            {orderType === 'limit' && (
              <View style={styles.confirmRow}>
                <Text style={styles.confirmLabel}>价格</Text>
                <Text style={styles.confirmValue}>¥{price}</Text>
              </View>
            )}
            <View style={styles.confirmRow}>
              <Text style={styles.confirmLabel}>数量</Text>
              <Text style={styles.confirmValue}>{quantity} 股/币</Text>
            </View>
            <View style={styles.confirmRow}>
              <Text style={styles.confirmLabel}>预估金额</Text>
              <Text style={[styles.confirmValue, { fontWeight: 'bold' }]}>
                ¥{totalAmount.toLocaleString('zh-CN')}
              </Text>
            </View>

            <View style={styles.confirmDivider} />

            <View style={styles.confirmButtonRow}>
              <TouchableOpacity
                style={styles.confirmCancelButton}
                onPress={() => setShowConfirm(false)}
              >
                <Text style={styles.confirmCancelText}>取消</Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={[
                  styles.confirmSubmitButton,
                  { backgroundColor: side === 'buy' ? '#FF5252' : '#4CAF50' },
                ]}
                onPress={handleConfirm}
              >
                <Text style={styles.confirmSubmitText}>确认{side === 'buy' ? '买入' : '卖出'}</Text>
              </TouchableOpacity>
            </View>
          </View>
        </View>
      </Modal>
    </View>
  );
}

// ── 样式 ──────────────────────────────────────────────────
const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#141414',
  },
  scrollContent: {
    padding: 16,
  },
  label: {
    color: '#888',
    fontSize: 13,
    marginBottom: 8,
    marginTop: 16,
  },
  symbolSelector: {
    backgroundColor: '#1E1E1E',
    borderRadius: 10,
    padding: 16,
    borderWidth: 1,
    borderColor: '#2A2A2A',
  },
  selectedSymbolRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  selectedSymbolName: {
    color: '#E0E0E0',
    fontSize: 16,
    fontWeight: '600',
  },
  selectedSymbolCode: {
    color: '#666',
    fontSize: 12,
    marginTop: 2,
  },
  selectedSymbolPrice: {
    color: '#4FC3F7',
    fontSize: 18,
    fontWeight: 'bold',
  },
  placeholder: {
    color: '#555',
    fontSize: 15,
  },
  sideRow: {
    flexDirection: 'row',
    gap: 12,
  },
  sideButton: {
    flex: 1,
    backgroundColor: '#1E1E1E',
    borderRadius: 10,
    paddingVertical: 14,
    alignItems: 'center',
    borderWidth: 1,
    borderColor: '#2A2A2A',
  },
  sideButtonBuyActive: {
    backgroundColor: 'rgba(255, 82, 82, 0.15)',
    borderColor: '#FF5252',
  },
  sideButtonSellActive: {
    backgroundColor: 'rgba(76, 175, 80, 0.15)',
    borderColor: '#4CAF50',
  },
  sideButtonText: {
    color: '#888',
    fontSize: 16,
    fontWeight: '600',
  },
  sideButtonTextActive: {
    color: '#E0E0E0',
  },
  typeRow: {
    flexDirection: 'row',
    gap: 12,
  },
  typeButton: {
    flex: 1,
    backgroundColor: '#1E1E1E',
    borderRadius: 10,
    paddingVertical: 12,
    alignItems: 'center',
    borderWidth: 1,
    borderColor: '#2A2A2A',
  },
  typeButtonActive: {
    borderColor: '#4FC3F7',
    backgroundColor: 'rgba(79, 195, 247, 0.1)',
  },
  typeButtonText: {
    color: '#888',
    fontSize: 14,
    fontWeight: '600',
  },
  typeButtonTextActive: {
    color: '#4FC3F7',
  },
  inputRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  adjustButton: {
    backgroundColor: '#1E1E1E',
    borderRadius: 8,
    width: 44,
    height: 44,
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 1,
    borderColor: '#2A2A2A',
  },
  adjustButtonText: {
    color: '#E0E0E0',
    fontSize: 22,
    fontWeight: 'bold',
  },
  input: {
    flex: 1,
    backgroundColor: '#1E1E1E',
    borderRadius: 10,
    padding: 14,
    color: '#E0E0E0',
    fontSize: 16,
    textAlign: 'center',
    borderWidth: 1,
    borderColor: '#2A2A2A',
  },
  quickQtyRow: {
    flexDirection: 'row',
    gap: 8,
    marginTop: 8,
  },
  quickQtyButton: {
    flex: 1,
    backgroundColor: '#1E1E1E',
    borderRadius: 8,
    paddingVertical: 10,
    alignItems: 'center',
    borderWidth: 1,
    borderColor: '#2A2A2A',
  },
  quickQtyText: {
    color: '#4FC3F7',
    fontSize: 13,
    fontWeight: '600',
  },
  summaryCard: {
    backgroundColor: '#1E1E1E',
    borderRadius: 10,
    padding: 14,
    marginTop: 16,
  },
  summaryRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  summaryLabel: {
    color: '#888',
    fontSize: 14,
  },
  summaryValue: {
    color: '#E0E0E0',
    fontSize: 18,
    fontWeight: 'bold',
  },
  submitButton: {
    borderRadius: 10,
    paddingVertical: 16,
    alignItems: 'center',
    marginTop: 20,
  },
  submitButtonBuy: {
    backgroundColor: '#FF5252',
  },
  submitButtonSell: {
    backgroundColor: '#4CAF50',
  },
  submitButtonDisabled: {
    opacity: 0.6,
  },
  submitButtonText: {
    color: '#FFF',
    fontSize: 18,
    fontWeight: 'bold',
  },
  hotSymbolRow: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#1E1E1E',
    borderRadius: 8,
    padding: 14,
    marginBottom: 8,
  },
  hotSymbolInfo: {
    flex: 1,
  },
  hotSymbolName: {
    color: '#E0E0E0',
    fontSize: 15,
    fontWeight: '600',
  },
  hotSymbolCode: {
    color: '#666',
    fontSize: 12,
    marginTop: 2,
  },
  hotSymbolPrice: {
    color: '#E0E0E0',
    fontSize: 15,
    marginRight: 12,
  },
  hotSymbolChange: {
    fontSize: 14,
    fontWeight: '600',
    width: 70,
    textAlign: 'right',
  },
  // Modal
  modalOverlay: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.7)',
    justifyContent: 'flex-end',
  },
  modalContent: {
    backgroundColor: '#1E1E1E',
    borderTopLeftRadius: 16,
    borderTopRightRadius: 16,
    maxHeight: '70%',
    paddingBottom: 30,
  },
  modalHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: 16,
    borderBottomWidth: 1,
    borderBottomColor: '#2A2A2A',
  },
  modalTitle: {
    color: '#E0E0E0',
    fontSize: 18,
    fontWeight: 'bold',
  },
  modalClose: {
    color: '#888',
    fontSize: 20,
  },
  modalSymbolRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: 16,
    borderBottomWidth: 1,
    borderBottomColor: '#222',
  },
  modalSymbolName: {
    color: '#E0E0E0',
    fontSize: 15,
    fontWeight: '600',
  },
  modalSymbolCode: {
    color: '#666',
    fontSize: 12,
    marginTop: 2,
  },
  modalSymbolPrice: {
    color: '#E0E0E0',
    fontSize: 15,
  },
  modalSymbolChange: {
    fontSize: 13,
    marginTop: 2,
  },
  // 确认弹窗
  confirmCard: {
    backgroundColor: '#1E1E1E',
    borderRadius: 16,
    padding: 24,
    margin: 24,
  },
  confirmTitle: {
    color: '#FFD700',
    fontSize: 20,
    fontWeight: 'bold',
    textAlign: 'center',
  },
  confirmDivider: {
    height: 1,
    backgroundColor: '#2A2A2A',
    marginVertical: 16,
  },
  confirmRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginBottom: 12,
  },
  confirmLabel: {
    color: '#888',
    fontSize: 14,
  },
  confirmValue: {
    color: '#E0E0E0',
    fontSize: 14,
  },
  confirmButtonRow: {
    flexDirection: 'row',
    gap: 12,
  },
  confirmCancelButton: {
    flex: 1,
    backgroundColor: '#2A2A2A',
    borderRadius: 10,
    paddingVertical: 14,
    alignItems: 'center',
  },
  confirmCancelText: {
    color: '#888',
    fontSize: 16,
    fontWeight: '600',
  },
  confirmSubmitButton: {
    flex: 1,
    borderRadius: 10,
    paddingVertical: 14,
    alignItems: 'center',
  },
  confirmSubmitText: {
    color: '#FFF',
    fontSize: 16,
    fontWeight: 'bold',
  },
});

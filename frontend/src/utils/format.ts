import dayjs from 'dayjs'

const SYMBOLS: Record<string, string> = {
  CNY: '¥', USD: '$', EUR: '€', GBP: '£', JPY: 'JP¥', CAD: 'C$', AUD: 'A$', MXN: 'MX$', HKD: 'HK$', SGD: 'S$',
}

export function currencySymbol(currency?: string | null): string {
  if (!currency) return ''
  return SYMBOLS[currency] ?? `${currency} `
}

export function fmtNumber(v: number | string | null | undefined, digits = 2): string {
  if (v === null || v === undefined || v === '') return '-'
  const n = typeof v === 'string' ? Number(v) : v
  if (Number.isNaN(n)) return '-'
  return n.toLocaleString('zh-CN', { minimumFractionDigits: digits, maximumFractionDigits: digits })
}

export function fmtMoney(v: number | string | null | undefined, currency?: string | null, digits = 2): string {
  if (v === null || v === undefined || v === '') return '-'
  const n = typeof v === 'string' ? Number(v) : v
  const sign = n < 0 ? '-' : ''
  return `${sign}${currencySymbol(currency)}${fmtNumber(Math.abs(n), digits)}`
}

export function fmtInt(v: number | null | undefined): string {
  if (v === null || v === undefined) return '-'
  return v.toLocaleString('zh-CN')
}

export function fmtPercent(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined) return '-'
  return `${v.toFixed(digits)}%`
}

export function fmtDate(v?: string | null): string {
  return v ? dayjs(v).format('YYYY-MM-DD') : '-'
}

export function fmtDateTime(v?: string | null): string {
  return v ? dayjs(v).format('YYYY-MM-DD HH:mm') : '-'
}

export function profitColor(v?: number | null): string | undefined {
  if (v === null || v === undefined) return undefined
  return v < 0 ? '#cf1322' : v > 0 ? '#389e0d' : undefined
}

export const today = () => dayjs().format('YYYY-MM-DD')
export const daysAgo = (n: number) => dayjs().subtract(n, 'day').format('YYYY-MM-DD')

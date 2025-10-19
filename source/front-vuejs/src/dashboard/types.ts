export type AlertType = 'info' | 'error' | 'warning' | 'success'

export interface AlertItem {
  id: number
  message: string
  type: AlertType
  autoClose: boolean
  visible: boolean
}

export interface CreateButtonState {
  text: string
  disabled: boolean
  showIcon: boolean
}


variable "deepseek_api_key" {
  description = "DeepSeek API Key (主模型)"
  type        = string
  sensitive   = true
}

variable "minimax_api_key" {
  description = "MiniMax API Key (视觉模型)"
  type        = string
  sensitive   = true
}

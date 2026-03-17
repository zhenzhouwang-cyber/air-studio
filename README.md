# Core Pipeline (Temporary: Optimize Only)

当前已稳定跑通链路：
- 输入描述
- Ark 优化 Prompt
- 前端展示优化结果

图片生成（Gemini）与 R2 上传暂时停用，等你确认优化链路稳定后再恢复。

## 启动

```bash
cd /d E:\Opencode\lovart
npm install
pip install -r backend/requirements.txt
npm run dev:full
```

## 环境变量（最小必填）

`.env` 需要：

```env
ARK_API_KEY=...
ARK_ENDPOINT_ID=ep-...
ARK_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
```

## 自测接口

- `GET http://127.0.0.1:8000/api/health`
- `POST http://127.0.0.1:8000/api/optimize`

请求示例：

```json
{
  "description": "一个高端品牌logo设计，平面、二维、专业、现代、大气",
  "quality_tier": "high",
  "output_language": "en"
}
```

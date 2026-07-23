# Phase 14 Refresh Token Cookie 安全测试计划

## 1. 目标

消除公开部署前的浏览器令牌暴露面：Refresh Token 只通过 `HttpOnly` Cookie 传输，不再进入 JSON 响应、JavaScript 内存或 `sessionStorage`。Access Token 仍保持短时内存态，并继续支持 Refresh Token 单次旋转、并发重放拒绝和服务端注销。

## 2. 服务端契约

- 注册、登录和刷新成功时返回 `trip_pilot_refresh` Cookie，属性必须包含 `HttpOnly`、可配置但生产默认开启的 `Secure`、`SameSite=Strict`、`Path=/api/auth` 和与 Refresh Token TTL 一致的 `Max-Age`。
- JSON 响应不得包含 `refreshToken`；刷新和注销只从 Cookie 读取令牌，请求体中的令牌不再被接受。
- 刷新成功必须旋转 Cookie；旧 Cookie 重放返回 401。注销无论 Cookie 是否有效都清除浏览器 Cookie，有效令牌同时在数据库撤销。

## 3. Web 契约

- Web 不再声明、读写或删除 Refresh Token 存储键，也不把令牌放入请求体。
- 启动时通过 Cookie 尝试恢复会话；401 安全回到访客态，网络失败不得伪造登录态。
- Access Token 过期时只允许一个 Cookie 刷新请求在途；登出后迟到的刷新结果不能恢复本地会话。

## 4. 验收门禁

- Java 鉴权集成测试覆盖 Cookie 属性、响应脱敏、旋转、过期、注销和并发重放。
- Vue API 与应用测试覆盖无浏览器存储、无请求体刷新/注销、自动恢复和竞态保护。
- Java、Vue 全量测试与生产构建通过，仓库搜索不存在 `sessionStorage` Refresh Token 持久化。

## 完成记录

注册、登录、轮换、重放拒绝、注销清除、首次恢复和注销竞态均已通过自动化测试。Java 仅用 Cookie 接收刷新令牌，Vue 使用同源凭据且不再声明任何 Refresh Token 存储键。

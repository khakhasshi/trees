# 树苗管理网站（Flask + SQLite）

## 功能
- 树苗信息管理：照片、编号、高度、树冠宽度、价格、是否售出
- 高级筛选：按编号、价格区间、高度区间、冠幅区间、售出状态组合检索
- 批量导入：支持 Excel/CSV 一次导入（新增或按编号更新）
- 图片上传：网页直接上传，自动重命名为“编号.后缀”
- 统计看板：总库存、未售数量、已售金额、均价、规格分布
- 售出记录：售出日期、客户、联系方式、备注
- 导出报表：按当前筛选结果一键导出 Excel/PDF
- 权限与登录：管理员/员工角色
- 操作日志与回收站：软删除、可恢复、可追溯
- SQLite 本地数据库存储（`trees.db`）

## 已内置示例数据
- 编号 0523，高度 1.2 米，树冠宽度 2.2 米，价格 3800，未售出，图片 `0523.jpg`
- 编号 0506，高度 1.2 米，树冠宽度 1.6 米，价格 3800，未售出，图片 `0506.jpg`

## 运行方式
1. 安装依赖
   ```bash
   pip install -r requirements.txt
   ```
2. 启动服务
   ```bash
   python app.py
   ```
3. 浏览器打开
   ```
    http://127.0.0.1:7006
   ```

## 默认账号
- 管理员：`admin` / `admin123`
- 员工：`employee` / `emp123`

> 建议首次登录后在数据库中修改默认密码。

## 批量导入模板字段
支持中英文字段名（示例）：
- 必填：`code/编号`、`height/高度`、`crown_width/树冠宽度/冠幅`、`price/价格`
- 可选：`sold/是否售出`、`photo/照片`、`sold_date/售出日期`、`customer_name/客户`、`customer_contact/联系方式`、`notes/备注`

## 局域网访问
- 已默认监听所有网卡（`0.0.0.0:7006`）。
- 在同一局域网其他设备访问：
   ```
   http://你的电脑局域网IP:7006
   ```
- 可用以下命令查看本机 IP（macOS）：
   ```bash
   ipconfig getifaddr en0
   ```

- 如需改端口：
   ```bash
   PORT=9000 python app.py
   ```

## Ubuntu 持久化部署
使用一键脚本：
```bash
sudo bash deploy_ubuntu.sh
```
部署后服务名：`trees-app`

- 状态：`systemctl status trees-app`
- 日志：`journalctl -u trees-app -f`

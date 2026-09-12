# 局域网访问

仅用于可信局域网。所有访问者共享报告、知识库和模型额度，当前没有用户权限隔离。不要配置路由器公网端口转发，不开放 PostgreSQL 的 5432 端口。

1. 在原服务窗口按 Ctrl+C 停止服务。
2. 在项目目录执行 `start-lan.cmd`，保持窗口开启。原来的 `start-visible.cmd` 仍只允许本机访问。
3. Windows 网络应为你信任的“专用网络”。不要把公共 Wi-Fi 改成专用网络来绕过限制。
4. 首次设置防火墙，在管理员 PowerShell 中执行：

```powershell
Set-Location D:\yidui\env\ckos
.\enable-lan-firewall.ps1
```

规则仅允许本地子网访问指定 Python 程序的 TCP 8000 端口，不会关闭防火墙。脚本需要管理员权限，不会自动修改网络类别。

5. 其他电脑或手机连接同一局域网，在浏览器访问 `http://服务器的局域网IP:8000/industry`。用 `ipconfig` 查看实际 Wi-Fi/以太网 IPv4，勿使用 WSL、VMware 的虚拟网卡地址。IP 可能因重连或 DHCP 改变。

无法连接时，先确认服务器本机可访问，再确认专用网络、防火墙规则、双方子网和路由器是否启用了客户端隔离。相同 Wi-Fi 名称不保证设备可以互访。

恢复仅本机访问：停止服务，执行 `start-visible.cmd`。可在管理员 PowerShell 运行 `.\enable-lan-firewall.ps1 -Remove` 删除本项目防火墙规则。

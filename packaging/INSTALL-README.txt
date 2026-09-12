力学虚拟实验室 2.1.1 — Windows 11 x64 离线版
公司名称：云南数美汇云软件有限公司

包含拉伸、压缩、扭转、弯曲、剪切、压杆失稳六类实验。
支持圆形/矩形截面和 Fe/Al 教学参数，内置 24 份标准试样记录。

安装：
1. 将完整 ZIP 包解压到一个文件夹。
2. 双击 install.cmd，选择安装父目录，安装完成后关闭安装窗口。
3. 双击桌面上的“力学虚拟实验室”快捷方式。

升级：先关闭旧版实验室，再运行 install.cmd；沿用原桌面入口。

便携运行：
双击 TensileLab 文件夹中的 TensileLab.exe。
请保留整个 TensileLab 文件夹，不能仅复制其中的 EXE 文件。

程序自带所需运行环境，不需要联网、管理员权限或另行安装 Python。
默认位置为当前用户的 LocalAppData\Programs\TensileLab，也可选择其他有写入权限的位置。
可以在 Windows“设置 → 应用”中卸载，或运行安装目录的 uninstall.ps1。
卸载不会删除用户自行导出的实验数据。

本程序为教学演示模型。材料、损伤参数及网格设置会影响仿真结果。

2.1 安装更新：双击 install.cmd 后选择安装父目录，程序放入 TensileLab 子目录。
可在命令行使用 install.ps1 -Quiet -InstallDirectory "D:\Apps\TensileLab" 指定完整路径。
卸载依据安装文件清单，保留用户自行导出的数据文件。

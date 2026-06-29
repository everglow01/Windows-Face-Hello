<div align="center">

# 👋 Face Hello

### 让普通 RGB 摄像头也能给 Windows 做人脸解锁   

![logo](README_image/facehello-wordmark.svg)

*面向不支持 Windows Hello 的笔记本、台式电脑前置摄像头 / USB 摄像头。*

*灵感源于作者拥有过的一台 Surface Pro 4 便携平板~*

<br>

[![Platform](https://img.shields.io/badge/系统-Windows%2010%20%7C%2011-0078D6?logo=windows&logoColor=white)](https://www.microsoft.com/windows)
[![Python](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)](https://www.python.org)
[![License](https://img.shields.io/badge/许可证-Apache%202.0-D22128?logo=apache&logoColor=white)](./LICENSE)
[![Recognition](https://img.shields.io/badge/识别-InsightFace%20ArcFace-FF6F00)](https://github.com/deepinsight/insightface)
[![Liveness](https://img.shields.io/badge/活体-MediaPipe-00BFA5?logo=google&logoColor=white)](https://developers.google.com/mediapipe)

**[🇬🇧 English](./README.md)**　｜　**[📐 设计与技术决策](./DESIGN_zh.md)**

</div>

---

## ⚠️ 使用前安全须知   

- 该项目仅考虑在**Windows10、11**系统上使用，不推荐在其他任何操作系统上使用该项目。   
- 项目涉及修改Windows服务等影响系统的操作，作者虽然已经加入大量安全保护也已经进行了实机验证，但仍有可能存在**无法登录、服务宕机、电脑蓝屏**等严重系统问题，虽然这些情况出现概率极小，但仍需注意。  
- 本项目使用OpenCV等视觉算法实现单RGB摄像头人脸识别解锁功能，也就是**类 Windows Hello**，但实际安全性远低于原版Windows Hello。单RGB摄像头不能像红外摄像头、深度摄像头感知空间信息，面对高质量视频、图片极有可能绕过安全检查进入系统。**请勿在存储敏感数据的工作电脑**使用该项目，存在极大风险，如造成巨大损失需个人自行承担后果。   
- 本项目视觉识别调用onnx模型在CPU上进行推理，对电脑硬件有一定要求，根据测试，不建议4核以下的CPU使用该项目，推理延迟将会明显提升，有违Windows hello原版快速解锁的初衷。  

---
## 💽网盘分发   

夸克网盘：   
链接：https://pan.quark.cn/s/db1464cf9c2d?pwd=afnw       
提取码：afnw     

---    

## 📋 环境要求

- **Windows 10 / 11(x64)**
- 一个可用的 **RGB 摄像头**
- **4 核及以上 CPU**:识别在 CPU 上跑 onnx 推理,核心太少解锁延迟会明显变大,有违快速解锁的初衷
- 部分进阶功能(写 LSA 密码、装服务)需要**管理员**终端(PowerShell)

---

## 🚀 安装与使用(推荐:一键安装包)

普通用户不需要装 Python / uv,在Release界面下载提供的安装包即可

1. 到 [Releases](https://github.com/everglow01/Windows-Face-Hello/releases) 下载最新版的 `FaceHello-Setup-x.y.z.exe`。
2. 右键**以管理员身份运行**,跟着中文向导一路下一步。安装器会自动帮你注册并启动后台认证服务、注册锁屏凭据提供程序、建好数据目录。
3. 装好后从开始菜单或桌面打开「FaceHello 管理台」(初次请用管理员权限),录入人脸、设好登录密码,就能在锁屏用脸解锁了。

> 识别模型已经全部打包进安装包,安装过程无需联网下载。

**卸载**:从 Windows「设置 → 应用」或开始菜单里的「卸载 FaceHello」即可完成卸载，卸载包括软件本地和所有本地数据，不留任何残余文件在本地。

---

## 🛠️ 开发环境    

想通过源码运行控制台和服务、或者参与开发的话:

- **Python 3.11**(项目要求 `>=3.10,<3.12`)
- [**uv**](https://docs.astral.sh/uv/)(包 / 虚拟环境管理)

```powershell
git clone https://github.com/everglow01/Windows-Face-Hello.git
cd Windows-Face-Hello

uv sync                                   # 创建 .venv 并安装依赖(非 base 环境)
uv run python scripts/offline_check.py    # 离线自检(不需摄像头/显示器),全 [ok] 即正常
uv run python -m app.main                 # 启动管理台 GUI（初次使用必须使用管理员权限）
```

> 首次运行会自动下载模型到 `models/`:InsightFace `buffalo_l`(识别 + 检测,约 191MB)、MediaPipe `face_landmarker.task`(活体,约 3.7MB)。    

详细的开发者文档以及contribute指南见[contribute_zh.md](./contribute_zh.md)

---

## 🖥️ 管理台 GUI 使用介绍

管理员权限启动安装好的应用，进入管理台桌面应用：   

![GUI](README_image/GUI.png)

1. **录入** — 用户名默认填当前 Windows 账户名（即电脑锁屏界面显示的文字）;正对摄像头采集若干合格帧,取平均特征作为模板。已录入用户的查看 / 删除也在本页。
   > 用户名必须等于你的 Windows 登录账户名,锁屏解锁才能对上(微软账户走本地登录名)。
   >不清楚账户名可以Win+L查看锁屏界面显示的用户名称，一般来说二者一样
   > 💡 **建议:同一用户多录几条模板。** 首次「开始录入」后,换不同**角度、光照、妆容 / 发型、戴不戴眼镜**等场景,点「**补录角度**」按钮各补录一条(同一用户名下可存多条模板,解锁时自动取最相似的一条)。录 **2 条以上**能明显提升不同场景下的解锁成功率、减少偶发刷不开。可在「设置」页调每人模板上限。
2. **测试解锁** — 按提示完成随机活体动作(眨眼 N 次 / 向左 / 向右转头),通过后做识别比对,显示相似度与结果。
3. **设置** — 选择摄像头(带「测试」按钮预览所选那台,多摄像头机器很有用);调匹配阈值、转头角度、眨眼次数、人脸有效期;开关「活体检测」与「被动反欺骗」。
4. **服务与凭据** — 设置锁屏解锁要用的登录密码(写入 LSA Secret)、一键安装 / 启停认证服务。**需管理员权限**,否则相关按钮置灰。  

*初次进行录脸和测试会出现卡顿，属正常现象。*    

*GUI界面右下角将显示模型加载状况，建议稍作等待等模型加载完成后再进行人脸录入和识别测试。*  

如需标定活体阈值(实时显示 EAR / yaw,退出给建议值):

```powershell
uv run python -m scripts.liveness_tune
```

---

## 🔓 锁屏解锁实现

完整解锁链路:锁屏「Face Unlock」磁贴 →(命名管道)→ LocalSystem 系统服务 → InsightFace 识别 → 读取 LSA 中保存的密码 → 打包 Kerberos 凭据真解锁。本地账户与微软账户(MSA 本地登录)均已端到端验证。**在作者实体机上已得到完整验证可用。**

> 刷脸失败时,按磁贴上的 **→** 按钮可再试一次——共 **3 次**机会,用尽后回退到密码登录(系统密码 / PIN 始终保留)。

认证服务的命令(管理员;`<venv>` = `.venv\Scripts\python.exe`):

```powershell
<venv> winservice_main.py install --startup auto   # 注册系统服务并设开机自启
<venv> winservice_main.py start | stop | remove     # 起 / 停 / 删
```
上述命令一般来说不用手动启动，在前面的GUI界面中可以一键安装启动，此处做开发调试用。

如果你是从源码开发、想自己编译锁屏磁贴那块的 C++ 凭据提供程序(CP),需要 VS2022 并勾选「使用 C++ 的桌面开发」,**用 PowerShell 编译**:

```powershell
MSBuild.exe cp\FaceHelloCP.sln /p:Configuration=Release /p:Platform=x64
# 产物在 cp\x64\Release\FaceHelloCP.dll,再用 regsvr32 注册
```

> ⚠️ 注册 CP、真机测试前**务必**先打系统还原点或 VM 快照,并留一个备用管理员账户。更多构建与排错细节见 [cp/README.md](./cp/README.md)。


---

## ⚙️ 工作原理(简述)

```
摄像头(OpenCV) → 活体检测(MediaPipe FaceLandmarker:EAR 眨眼 + solvePnP 转头)
              → 人脸检测 + 识别(InsightFace ArcFace,512 维特征)
              → 余弦相似度比对人脸库 → 通过 / 拒绝
```

- 核心库 `face_hello/` 无 GUI 依赖,被管理台、服务、脚本共用。
- 锁屏场景下,识别在常驻的 LocalSystem 服务里完成;C++ 凭据提供程序只负责 UI 与提交凭据,二者通过本地命名管道通信。

---  

## 🖼️ 自定义锁屏界面头像

你可以在默认路径 `C:\ProgramData\FaceHello` 下放一张自己的头像图片。程序会取这个目录下的**第一张**图片,缩放裁切成正方形贴到锁屏磁贴上。

- 支持 **PNG / JPG / BMP** 格式,建议直接放一张正方形图,免得边缘被裁掉。
- 纯 ASCII 路径——锁屏下以 SYSTEM 身份运行的凭据提供程序才读得到
- 读不到图片或解码失败时,磁贴会自动回退成默认的纯蓝色占位图,不影响解锁功能。

![touxiang](README_image/touxiang.png)

## 🔐 安全与隐私

- 人脸库存的是**特征向量,不是照片**,且用 Windows DPAPI 加密落盘在本地 `data/`,不上传任何云端服务器，确保人脸数据隐私安全。
- 登录密码保存在 **LSA Secret**,由凭据提供程序在 SYSTEM 上下文自行读取,**永不经过进程间通信**。
- RGB 单目活体不能判断高质量图片、视频流，**请不要在可能被他人接触的机器上使用该项目**，如出现数据泄露、丢失等一切问题，皆属使用者个人操作失误，以及不了解此项目风险的后果，需要自行承担。
- 关闭**活体检测**后，启动速度将压缩到1s内，获得几乎无感的启动，但出于安全考虑，我们仍不推荐您关闭。

---

## 📂 目录结构

```
face_hello/        核心库(无 Qt 依赖)
  camera.py          摄像头采集(带冷启动 / 唤醒重试)
  detector.py        InsightFace 检测 + 512 维特征
  matcher.py         余弦相似度比对
  liveness.py        FaceLandmarker → EAR 眨眼 + solvePnP 转头 + 随机挑战
  enroll.py          多帧平均特征录入
  store.py           DPAPI 加密人脸库 + 设置
  auth.py            认证编排(活体 → 识别)状态机
  service.py         命名管道认证服务端
  win_service.py     LocalSystem Windows 服务封装
  cred_vault.py      LSA Secret 读写(登录密码)
app/               PySide6 管理台(main.py + 后台 workers.py)
cp/                C++ Credential Provider(锁屏磁贴,需 VS 编译)
scripts/           offline_check.py 等工具脚本
data/              加密人脸库(gitignored)
models/            模型权重(gitignored)
```

---

## 🚧 已知限制

- 防伪能力受限于 RGB 单目(见上文安全说明)，可能存在被有心之人通过不法手段绕过的可能，再次强调，请不要在存放敏感数据的电脑上使用。
- 首次冷启动需要从磁盘加载约 191MB 识别模型,有数秒开销（现代CPU上约2s）;睡眠唤醒后摄像头需要几秒重新枚举(已加重试)。
- 工作目录含中文路径时,已对 OpenCV / MediaPipe 做特殊处理,但仍可能存在编码错乱问题。
- 安装包体积和应用本体体积受限于Python相关依赖包，体积较大

---   

## ❓ 常见问题 Q&A    
**Q：在控制台应用中可以打开摄像头并且准确识别人脸，为什么电脑锁定或冷启动后经常出现无法打开摄像头导致无法使用Face Hello功能？**    

A：1.部分USB摄像头或笔记本内置相机在锁定界面*不会供电*，导致OpenCV无法抓取到摄像头，请确认在锁屏界面或电脑冷启动(刚刚开机、睡眠后重新唤醒等)时，您的相机设备处于供电状态；2.对于部分厂商的笔记本电脑，在没有连接电源适配器或进入省电模式下可能关闭摄像头，需要强制开启；3.确保您在Windows设置中开启了摄像头权限；4.确保在锁屏界面相机没有被其他应用或程序占用；5.极少数外接摄像头会出于安全考虑拒绝在锁屏界面访问，这种情况无解，只能更换摄像头。  

**Q：在锁屏界面显示“未启动服务”，无法使用面部解锁**   

A：从管理员权限进入控制台界面，在“服务与凭据”这一栏中注意看服务运行状态，如果未运行请点击运行按钮，如果运行状态是“正在运行”，请提交issue和您电脑的运行环境以便我们进一步确认问题。    

**Q：为什么我的人脸识别验证在锁屏界面不能稳定使用，在启动Face Hello时启动很久最后失败，但有时又能正常运行？**     

A：这的确是当前程序的一个bug，我们已经对启动慢、有时候启动不了的问题进行了修复和优化，在作者测试的几台电脑上出现这一问题的概率极低，几乎为0，如果您经常性遇到这样的问题，请您提交issue便于我们排查。出现这样的bug可能是守护线程没有正常运行、相机/摄像头索引不稳定等等。     

**Q：进行Windows更新后，重启电脑为什么无法使用 Face Hello？**   

A：此乃正常现象，Windows更新后一般会刷新 WIndows 服务，此时可能导致 Face Hello 服务挂起，通过密码解锁进入系统后，下次锁屏时即可恢复服务，不需要进入控制台再运行一次服务。   

## 📝 TODO   
1.优化启动速度，模型加载速度，服务启动速度(OpenCV DNN)     
2.美化Pyside6前端或进行重构      
3.进一步提升安全性，包括登录凭证与单RGB保护     
4.详细使用文档(?)    
5.GPU推理支持      

## 📄 许可证
Apache-2.0(见 LICENSE);因捆绑的 InsightFace 模型仅限非商业,发行版为非商业用途,详见 THIRD_PARTY_LICENSES.md    

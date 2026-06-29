# app/assets

放管理台的自定义资源。

## facehello.ico —— 应用图标

把你的图标存为 **`facehello.ico`** 放在本目录,即生效于:

- 运行时窗口 + 任务栏图标(`app/main.py` 的 `_app_icon()` 读取);
- 安装后的开始菜单 / 桌面快捷方式、卸载项图标(`installer/FaceHello.iss` 的 `IconFilename` / `UninstallDisplayIcon`)。

缺文件时两处都优雅回退到默认图标,不报错。

### 怎么做一个

1. 准备一张**正方形** logo(建议 256×256、透明背景的 PNG)。
2. 转成**多尺寸 `.ico`**(含 16/32/48/256,任务栏和高 DPI 才清晰):
   - 在线转换站(搜 "png to ico"),或
   - Pillow:`uv run --with pillow python -c "from PIL import Image; Image.open('logo.png').save('app/assets/facehello.ico', sizes=[(16,16),(32,32),(48,48),(256,256)])"`
3. 存为 `app/assets/facehello.ico`,提交入库(安装器会随 `app/` 一起打包)。

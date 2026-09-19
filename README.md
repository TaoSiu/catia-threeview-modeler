# catia-threeview-modeler

看一张工程三视图，在 CATIA V5 里自动把三维模型建出来，最后存成 `.CATProduct`。

起因很简单：作业里那种"照着三视图建个支座"的题，尺寸都标得清清楚楚，手动在 CATIA 里拉草图、标约束、打孔、倒圆角，重复劳动又容易标错。于是就写了这一套：把三视图读成一棵特征树（JSON），再由脚本驱动 CATIA 把树"长"出来。

![示例三视图](examples/sample_threeview.png)

## 它建出来的模型长什么样

不是那种导进来就改不了的死实体——草图、凸台、孔都是带参数的特征，特征树里名字也规矩（`Sketch_base`、`Pad_base`、`Hole_1` 这种），双击就能改尺寸。基准面跟 XY/YZ/ZX 对正，原点落在几何中心或基准孔上。一张图一个零件就挂一个 `.CATPart`，装配图就拆成几个 `.CATPart` 按位置摆好。

尺寸看不清楚或者三视图对不上的时候，它不会瞎编一个数硬建，而是停下来问。

## 环境

- Windows，CATIA V5 装着并且开着（R2016 以后的版本，走 COM 接口驱动）
- Python 3.8+，依赖就两个：

```bash
pip install pycatia pywin32
```

## 怎么跑

思路是三步：读图写 JSON → 校验 → 让 CATIA 建。

```bash
# 先确认环境没问题（CATIA 得先打开）
python scripts/check_env.py

# 校验特征 JSON，顺便打印一棵特征树出来给你核对
python scripts/validate_features.py your_model.json --out your_model.normalized.json

# 真刀真枪建模，顺便截一张预览图
python scripts/catia_build.py your_model.normalized.json --output-dir out/ --capture out/
```

JSON 怎么写、三视图怎么读，分别在这两个文件里：

- [`references/features_schema.md`](references/features_schema.md) — 特征 JSON 的字段说明
- [`references/threeview_reading.md`](references/threeview_reading.md) — 读图规则和"什么时候该停下来问用户"

完整的最小例子看 [`examples/sample_bracket.features.json`](examples/sample_bracket.features.json)。

## 目录

```
catia-threeview-modeler/
├── SKILL.md
├── scripts/
│   ├── check_env.py
│   ├── validate_features.py
│   ├── catia_build.py        # 真正驱动 CATIA 的那个
│   └── features_common.py    # 轮廓闭合检查、BRep 名拼接这些杂活
├── references/
└── examples/
```

## 能干到什么程度

直线、圆弧、整圆轮廓的拉伸凸台；通孔、沉头孔；矩形和圆形的凹槽；竖边圆角；45° 倒角；多零件装配定位——这些常见的都能搞定。

搞不定的：自由曲面、扫掠、加强筋这类特征；螺纹孔和埋头孔在 CATIA R21 的 API 上直接报错（试过了，不行，得手工补）；阵列特征目前就是多打几个孔凑合；也不自动出工程图。遇到曲面部分我会在建模前告诉你，剩下的手动加。

## License

MIT

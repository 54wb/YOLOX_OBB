import re
import torch.nn as nn
from copy import deepcopy
from loguru import logger
from .modules import *
from yolox.utils import make_divisible

def get_model(cfg='yoloxs.yaml', in_channel=3, num_classes=None, anchors=None, cfg_save_path=None):
    if isinstance(cfg, dict):
        yaml = cfg
    else:
        import yaml
        with open(cfg, encoding="ascii", errors="ignore") as f:
            yaml = yaml.safe_load(f)
    in_channel = yaml["in_channel"] = yaml.get("in_channel", in_channel)
    if num_classes and num_classes != yaml.get("num_classes", 80):
        logger.info("overriding modules.yaml num_classes={0} with num_classes={1}".format(yaml.get("num_classes", 80), num_classes))
        yaml["num_classes"] = num_classes
    if anchors:
        logger.info("overriding model.yam anchors={0} with nc={1}".format(yaml["anchors"], anchors))
        yaml["anchors"] = round(anchors)
    model, save = parse_model(deepcopy(yaml), [in_channel]);
    return model, save


def parse_model(cfg_dict, ch):
    # logger.info(f"\n{'':>3}{'from':>18}{'n':>3}{'params':>10}  {'module':<40}{'arguments':<30}")
    # print(f"\n{'':>3}{'from':>18}{'n':>3}{'params':>10}  {'module':<40}{'arguments':<30}")
    an = cfg_dict.get("anchors", None)
    nc = cfg_dict.get("num_classes", 80)
    gd = cfg_dict.get("depth_multiple", 0.5)
    gw = cfg_dict.get("width_multiple", 0.5)

    if an is not None:
        na = (len(an[0]) // 2) if isinstance(an, list) else an  # number of anchors
        no = na * (nc + 5)  # number of outputs = anchors * (classes + 5)
    else:
        no = nc + 5

    layers, save, c2 = [], [], ch[-1]  # layers, savelist, ch out
    for i, (f, n, m, args) in enumerate(cfg_dict['backbone'] + cfg_dict['head'] + cfg_dict["detect"]):  # from, number, module, args
        m = eval(m) if isinstance(m, str) else m  # eval strings
        kwargs = {}
        for j, a in enumerate(args):
            if isinstance(a, str) and re.match("^(kwargs\()(.*)(\))$", a) is not None:
                a = a.lstrip("kwargs")
                a = "dict" + a
                args.pop(j)
                kwargs.update(eval(a))
            else:
                try:
                    args[j] = eval(a) if isinstance(a, str) else a  # eval strings
                except NameError:
                    pass

        n = n_ = max(round(n * gd), 1) if n > 1 else n  # depth gain
        if m in [Conv, GhostConv, Bottleneck, GhostBottleneck, SPP, SPPF, DWConv, MixConv2d, Focus, CrossConv,
                 BottleneckCSP, C3, C3TR, C3SPP, C3Ghost]:
            c1, c2 = ch[f], args[0]
            if c2 != no:  # if not output
                c2 = make_divisible(c2 * gw, 8)

            args = [c1, c2, *args[1:]]
            if m in [BottleneckCSP, C3, C3TR, C3Ghost]:
                args.insert(2, n)  # number of repeats
                n = 1
        elif m is nn.BatchNorm2d:
            args = [ch[f]]
        elif m is Concat:
            c2 = sum(ch[x] for x in f)
        elif m in [DetectX, DetectV5, OBBDetectX]:
            kwargs["num_classes"] = nc
            args.append([ch[x] for x in f])
            # if isinstance(args[1], int):  # number of anchors
            #     args[1] = [list(range(args[1] * 2))] * len(f)
        elif m is Contract:
            c2 = ch[f] * args[0] ** 2
        elif m is Expand:
            c2 = ch[f] // args[0] ** 2
        else:
            c2 = ch[f]

        m_ = nn.Sequential(*(m(*args, **kwargs) for _ in range(n))) if n > 1 else m(*args, **kwargs)  # module
        t = str(m)[8:-2].replace('__main__.', '')  # module type
        np = sum(x.numel() for x in m_.parameters())  # number params
        m_.i, m_.f, m_.type, m_.np = i, f, t, np  # attach index, 'from' index, type, number params
        # logger.info(f'{i:>3}{str(f):>18}{n_:>3}{np:10.0f}  {t:<40}{str(args):<30}')  # print
        # print(f'{i:>3}{str(f):>18}{n_:>3}{np:10.0f}  {t:<40}{str(args):<30}')  # print
        save.extend(x % i for x in ([f] if isinstance(f, int) else f) if x != -1)  # append to savelist
        layers.append(m_)
        if i == 0:
            ch = []
        ch.append(c2)
    return nn.Sequential(*layers), sorted(save)
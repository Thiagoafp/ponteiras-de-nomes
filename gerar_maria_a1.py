"""Prato de teste: 2 x MARIA (laranja, PLA Basic) configurado para a Bambu Lab A1 0.4 (em vez da P1S).

Uso:  python gerar_maria_a1.py
Saída: saida/maria_A1/Ponteiras_prato_1.3mf
A configuração da A1 é lida dos perfis do Bambu Studio instalado (machine + filamento) e sobreposta ao project_settings da P1S.
"""
import json
import os
import shutil
import zipfile

os.environ.setdefault("PONTEIRAS_MESHER", "skimage")
import ponteiras_core as core

PERFIS = os.path.join(os.environ["APPDATA"], "BambuStudio", "system", "BBL")
MAQUINA = "Bambu Lab A1 0.4 nozzle"
FILAMENTO = "Bambu PLA Basic @BBL A1"
PROCESSO = "0.20mm Standard @BBL A1"
COR = "#FF9500FF"


def carregar(pasta, nome):
    """Perfil do Bambu Studio já resolvido: herda do pai (inherits) e junta os arquivos de include."""
    d = json.load(open(os.path.join(PERFIS, pasta, nome + ".json"), encoding="utf-8"))
    res = {}
    if d.get("inherits"):
        res.update(carregar(pasta, d["inherits"]))
    for inc in d.get("include", []):
        res.update(carregar(pasta, inc))
    res.update({k: v for k, v in d.items() if k not in ("include", "inherits")})
    return res


def config_a1():
    """Config da P1S (aceita pelo Studio) trocando só o que identifica a A1; listas mantêm o tamanho original."""
    cfg = json.load(open(core.BASE_CFG, encoding="utf-8"))
    maq = carregar("machine", MAQUINA)
    fil = carregar("filament", FILAMENTO)

    def pôr(k, v):
        if k not in cfg:
            return
        if isinstance(cfg[k], list):
            v = v[0] if isinstance(v, list) else v
            cfg[k] = [v] * len(cfg[k])
        else:
            cfg[k] = v if not isinstance(v, list) else v[0]

    for k in ("machine_start_gcode", "machine_end_gcode", "change_filament_gcode", "layer_change_gcode", "time_lapse_gcode",
              "printable_height", "nozzle_height", "extruder_clearance_dist_to_rod", "extruder_clearance_height_to_lid",
              "extruder_clearance_height_to_rod", "extruder_clearance_max_radius", "printer_structure", "retract_lift_below",
              "auxiliary_fan", "machine_load_filament_time", "machine_unload_filament_time"):
        if k in maq:
            pôr(k, maq[k])
    for k in ("textured_plate_temp", "textured_plate_temp_initial_layer", "hot_plate_temp", "hot_plate_temp_initial_layer"):
        if k in fil:
            pôr(k, fil[k])
    cfg["bed_exclude_area"] = []
    cfg["printer_settings_id"] = MAQUINA
    cfg["printer_model"] = "Bambu Lab A1"
    cfg["filament_settings_id"] = [FILAMENTO] * len(cfg["filament_settings_id"])
    cfg["print_settings_id"] = PROCESSO
    cfg["default_filament_profile"] = [FILAMENTO] * len(cfg["default_filament_profile"])
    cfg["default_print_profile"] = PROCESSO
    cfg["filament_colour"] = [COR] * len(cfg["filament_colour"])
    cfg["filament_multi_colour"] = [COR] * len(cfg["filament_multi_colour"])
    for k in ("print_compatible_printers", "compatible_printers"):
        if k in cfg:
            cfg[k] = []
    return cfg


saida = os.path.join(core.HERE, "saida")
pasta = os.path.join(saida, "maria_A1")
p = core.Params(caixa="maiusculas")
arqs = core.gerar_tudo([("MARIA", 2, p)], saida, log=lambda m: print(m.encode("ascii", "replace").decode()),
                       pasta_pedido=pasta, material="PLA")
for a in arqs:
    tmp = a + ".tmp"
    with zipfile.ZipFile(a) as zin, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for it in zin.infolist():
            data = zin.read(it.filename)
            if it.filename == "Metadata/project_settings.config":
                data = json.dumps(config_a1(), ensure_ascii=False, indent=4).encode("utf-8")
            zout.writestr(it, data)
    shutil.move(tmp, a)
print("Pronto:", pasta)

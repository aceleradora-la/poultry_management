import { Component, useState, onWillStart, onPatched } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { user } from "@web/core/user";
import { scanBarcode } from "@web/core/barcode/barcode_dialog";
import { isBarcodeScannerSupported } from "@web/core/barcode/barcode_video_scanner";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { PoultryEggParts } from "./poultry_egg_parts";
import { PoultryFarmData } from "./poultry_farm_data";

const MODEL = "poultry.weight.record";
// Un peso que se aleja más que esto del promedio pide confirmación antes de guardarse:
// atrapa errores de tipeo (4523 por 1523: en el teclado el 4 está arriba del 1, o 152
// por 1520) sin molestar con las aves reales, que rara vez se alejan tanto.
const OUTLIER_PCT = 30;
const EGG_MODEL = "poultry.egg.collection";
const CLOSE_MODEL = "poultry.coop.close";

/**
 * App Avícola Campo, pensada para el celular: inicio → pesadas enviadas a pesar →
 * tarjetas por jaula → pesos de una jaula. La jaula se abre escaneando su QR (cámara
 * del navegador o de la app de Odoo) o escribiendo el código. Solo se escribe el peso:
 * Siguiente/Enter pasa a la ave de abajo. Los avisos se ven en la tarjeta, no mientras
 * se carga.
 */
export class PoultryWeighing extends Component {
    static template = "poultry_management.PoultryWeighing";
    static components = { PoultryEggParts, PoultryFarmData };
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.dialog = useService("dialog");
        this.notification = useService("notification");
        this.pwa = useService("pwa");
        this.state = useState({
            screen: "home", // home | list | record | cage | eggs | farm
            records: [],
            eggSummary: "",
            farmSummary: "",
            record: null,
            cageId: null,
            manualCode: "",
            showManual: false,
            busy: false,
            // Funciones de Avícola Campo que tiene el usuario: cada una es un permiso propio
            // y combinable; el inicio muestra solo esas tarjetas.
            access: { weighing: false, collection: false, unclassified: false },
        });
        this.scannerSupported = isBarcodeScannerSupported();
        this.focusPending = false;
        onWillStart(async () => {
            await this.loadAccess();
            await this.loadHome();
        });
        onPatched(() => this.focusFirstEmpty());
    }

    // ------------------------------------------------------------------
    // Inicio
    // ------------------------------------------------------------------
    get todayLabel() {
        const label = new Date().toLocaleDateString("es-AR", { weekday: "long", day: "numeric", month: "long" });
        return label.charAt(0).toUpperCase() + label.slice(1);
    }

    get pendingLabel() {
        const pending = this.currentRecords;
        if (!pending.length) {
            const next = this.upcomingRecords[0];
            return next
                ? `Sin pesadas esta semana · próxima ${this.dayLabel(next.plan_week_start)}, ${next.coop}`
                : "Sin pesadas enviadas a pesar";
        }
        const coops = [...new Set(pending.map((rec) => rec.coop))].join(", ");
        const late = pending.filter((rec) => rec.late).length;
        const lateLabel = late ? ` · ${late} ${late === 1 ? "atrasada" : "atrasadas"}` : "";
        return `${pending.length} ${pending.length === 1 ? "pesada en curso" : "pesadas en curso"}${lateLabel} · ${coops}`;
    }

    /** Las que hay que pesar (atrasadas primero, ya vienen ordenadas del servidor). */
    get currentRecords() {
        return this.state.records.filter((rec) => rec.state === "in_progress");
    }

    /** Las próximas del Plan de Pesaje: informativas, se habilitan solas al empezar su semana. */
    get upcomingRecords() {
        return this.state.records.filter((rec) => rec.state === "planned");
    }

    get doneRecords() {
        return this.state.records.filter((rec) => rec.state === "registered");
    }

    /** "lun 16/11" a partir de una fecha ISO. */
    dayLabel(iso) {
        if (!iso) {
            return "";
        }
        const date = new Date(iso + "T12:00:00");
        const weekday = date.toLocaleDateString("es-AR", { weekday: "short" }).replace(".", "");
        return `${weekday} ${date.getDate()}/${date.getMonth() + 1}`;
    }

    /** Se ofrece instalar la app mientras no se esté ya dentro de la app instalada. */
    get canInstall() {
        return !this.pwa.isScopedApp && !window.matchMedia("(display-mode: standalone)").matches;
    }

    /** La misma página que Odoo usa para instalar Código de Barras, con nuestro nombre. */
    installApp() {
        const url =
            "/scoped_app?app_id=poultry_management&path=" +
            encodeURIComponent("scoped_app/avicola-campo") +
            "&app_name=" +
            encodeURIComponent("Avícola Campo");
        window.open(url, "_blank");
    }

    async goHome() {
        await this.loadHome();
        this.state.screen = "home";
        this.state.record = null;
        this.state.cageId = null;
    }

    async loadAccess() {
        const [weighing, collection, unclassified] = await Promise.all([
            user.hasGroup("poultry_management.poultry_field_weighing"),
            user.hasGroup("poultry_management.poultry_field_collection"),
            user.hasGroup("poultry_management.poultry_field_unclassified"),
        ]);
        Object.assign(this.state.access, { weighing, collection, unclassified });
    }

    get hasAnyAccess() {
        const access = this.state.access;
        return access.weighing || access.collection || access.unclassified;
    }

    /** Solo se piden los resúmenes de las funciones que tiene el usuario: las demás
     * darían error de permisos. */
    async loadHome() {
        const access = this.state.access;
        const jobs = [];
        if (access.weighing) {
            jobs.push(this.loadRecords());
        }
        if (access.collection) {
            jobs.push(this.loadEggSummary());
        }
        if (access.unclassified) {
            jobs.push(this.loadFarmSummary());
        }
        await Promise.all(jobs);
    }

    /** Resumen de las OF de Huevo sin Clasificar pendientes para la tarjeta del inicio. */
    async loadFarmSummary() {
        try {
            const data = await this.orm.call(CLOSE_MODEL, "poultry_mobile_pending", []);
            const missing = data.orders.filter((order) => !order.complete).length;
            const loaded = data.orders.length - missing;
            if (missing) {
                this.state.farmSummary = `${missing} OF por cargar: aves muertas y consumos`;
            } else if (loaded) {
                this.state.farmSummary = loaded === 1
                    ? "1 OF cargada, falta que la oficina la marque hecha"
                    : `${loaded} OF cargadas, falta que la oficina las marque hechas`;
            } else {
                this.state.farmSummary = "Nada pendiente";
            }
        } catch {
            this.state.farmSummary = "Aves muertas y consumos de la OF de Huevo sin Clasificar";
        }
    }

    openFarm() {
        this.state.screen = "farm";
        this.state.record = null;
        this.state.cageId = null;
    }

    /** Resumen de los partes de huevos del día para la tarjeta del inicio. */
    async loadEggSummary() {
        try {
            const data = await this.orm.call(EGG_MODEL, "poultry_mobile_coops", []);
            const counts = { done: 0, counted: 0, none: 0 };
            for (const item of data.coops) {
                const rec = item.record;
                if (!rec) {
                    if (item.live_bird_count) {
                        counts.none += 1;
                    }
                } else if (rec.state === "completed" || rec.state === "done") {
                    counts.done += 1;
                } else if (rec.state === "counted") {
                    counts.counted += 1;
                } else {
                    counts.none += 1;
                }
            }
            const parts = [];
            if (counts.none) {
                parts.push(`${counts.none} sin inicial`);
            }
            if (counts.counted) {
                parts.push(`${counts.counted} falta el bruto`);
            }
            if (counts.done) {
                parts.push(`${counts.done} ${counts.done === 1 ? "completo" : "completos"}`);
            }
            if (data.late.length) {
                parts.push(`${data.late.length} ${data.late.length === 1 ? "atrasado" : "atrasados"}`);
            }
            this.state.eggSummary = parts.length ? parts.join(" · ") : "Sin galpones con aves";
        } catch {
            this.state.eggSummary = "Huevos, mortandad y alimento desde el galpón";
        }
    }

    openEggs() {
        this.state.screen = "eggs";
        this.state.record = null;
        this.state.cageId = null;
    }

    async openList() {
        await this.loadList();
    }

    // ------------------------------------------------------------------
    // Datos
    // ------------------------------------------------------------------
    // No se llama "cage": las plantillas OWL escriben las variables de t-foreach sobre el
    // componente, y un getter con el mismo nombre que la variable del bucle la pisa.
    get currentCage() {
        const record = this.state.record;
        return record && record.cages.find((cage) => cage.cage_id === this.state.cageId);
    }

    get closedCount() {
        return this.state.record.cages.filter((cage) => cage.status === "closed").length;
    }

    get allClosed() {
        const cages = this.state.record.cages;
        return cages.length > 0 && this.closedCount === cages.length;
    }

    fmt(value) {
        return value ? Math.round(value).toLocaleString("es-AR") : "—";
    }

    pct(value) {
        return value.toLocaleString("es-AR", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
    }

    deviation(line) {
        const cage = this.currentCage;
        if (!line.weight_g || !cage || cage.bird_count < 2 || !cage.average_weight_g) {
            return "";
        }
        const dev = ((line.weight_g - cage.average_weight_g) / cage.average_weight_g) * 100;
        return (dev >= 0 ? "+" : "−") + this.pct(Math.abs(dev)) + " %";
    }

    progress(rec) {
        return rec.planned_bird_count ? Math.round((rec.bird_count / rec.planned_bird_count) * 100) : 0;
    }

    stateLabel(rec) {
        return rec.state === "registered" ? "A verificar" : "En curso";
    }

    async call(method, args = [], kwargs = {}) {
        this.state.busy = true;
        try {
            return await this.orm.call(MODEL, method, args, kwargs);
        } catch (error) {
            const message = (error.data && error.data.message) || error.message || String(error);
            this.notification.add(message, { type: "danger" });
            throw error;
        } finally {
            this.state.busy = false;
        }
    }

    // La pantalla se cambia ANTES de soltar la pesada actual: si se la suelta primero,
    // la plantilla de la pesada se vuelve a dibujar con record en null y se rompe.
    async loadRecords() {
        this.state.records = await this.call("poultry_mobile_list");
    }

    async loadList() {
        await this.loadRecords();
        this.state.screen = "list";
        this.state.record = null;
        this.state.cageId = null;
    }

    async openRecord(recordId) {
        this.state.record = await this.call("poultry_mobile_data", [[recordId]]);
        this.state.cageId = null;
        this.state.showManual = false;
        this.state.screen = "record";
    }

    async refreshRecord() {
        this.state.record = await this.call("poultry_mobile_data", [[this.state.record.id]]);
    }

    backToRecord() {
        this.state.cageId = null;
        this.state.screen = "record";
    }

    // ------------------------------------------------------------------
    // Jaulas
    // ------------------------------------------------------------------
    openCage(cageId) {
        this.state.cageId = cageId;
        this.state.screen = "cage";
        this.focusPending = true;
    }

    focusFirstEmpty() {
        if (!this.focusPending) {
            return;
        }
        this.focusPending = false;
        const inputs = [...document.querySelectorAll(".o_pw_cage input.o_pw_weight")];
        const target = inputs.find((input) => !input.value) || inputs[inputs.length - 1];
        if (target) {
            target.focus();
            target.select();
        }
    }

    async scan() {
        let code;
        try {
            code = await scanBarcode(this.env);
        } catch (error) {
            this.notification.add(
                "No se pudo abrir la cámara: " + (error.message || error) + ". Escribí el código.",
                { type: "warning" }
            );
            this.state.showManual = true;
            return;
        }
        if (code) {
            await this.openCode(code);
        }
    }

    async submitManual(ev) {
        ev.preventDefault();
        const code = this.state.manualCode.trim();
        if (code) {
            await this.openCode(code);
        }
    }

    async openCode(code) {
        const result = await this.call("poultry_mobile_find_cage", [[this.state.record.id], code]);
        if (result.error) {
            this.notification.add(result.error, { type: "warning" });
            return;
        }
        if (result.added) {
            await this.refreshRecord();
        }
        this.state.manualCode = "";
        this.state.showManual = false;
        this.openCage(result.cage_id);
    }

    applyCageState(result) {
        const cage = this.state.record.cages.find((c) => c.cage_id === result.cage.cage_id);
        if (cage) {
            Object.assign(cage, result.cage);
        }
        Object.assign(this.state.record, result.record);
    }

    // ------------------------------------------------------------------
    // Pesos
    // ------------------------------------------------------------------
    /** Peso contra el que se compara una ave: el promedio de las demás aves ya pesadas
     * en esta pesada (desde 3) o, antes, el de la pesada anterior del galpón. */
    referenceWeight(line) {
        const rec = this.state.record;
        let count = rec.bird_count || 0;
        let total = (rec.average_weight_g || 0) * count;
        if (line.weight_g > 0) {
            count -= 1;
            total -= line.weight_g;
        }
        if (count >= 3 && total > 0) {
            return total / count;
        }
        return rec.previous_average_g || 0;
    }

    /** true si el peso está dentro del rango o el operador confirma que es correcto. */
    confirmOutlier(line, value) {
        const reference = this.referenceWeight(line);
        if (!value || !reference) {
            return Promise.resolve(true);
        }
        const dev = ((value - reference) / reference) * 100;
        if (Math.abs(dev) <= OUTLIER_PCT) {
            return Promise.resolve(true);
        }
        return new Promise((resolve) => {
            this.dialog.add(
                ConfirmationDialog,
                {
                    title: "Peso fuera de rango",
                    body:
                        `Ave ${line.bird_no}: ${this.fmt(value)} g está ${dev > 0 ? "+" : "−"}${this.pct(Math.abs(dev))} % ` +
                        `del promedio (${this.fmt(reference)} g). ¿Es correcto?`,
                    confirmLabel: "Sí, guardar",
                    cancelLabel: "Corregir",
                    confirm: () => resolve(true),
                    cancel: () => resolve(false),
                },
                { onClose: () => resolve(false) }
            );
        });
    }

    /** Guarda el peso tipeado. Devuelve false si no se guardó (el operador eligió
     * corregirlo o falló el guardado): el campo vuelve al último peso guardado y queda
     * listo para tipear de nuevo. */
    async commitWeight(line, input) {
        const value = input.value === "" ? 0 : parseFloat(input.value);
        if (Number.isNaN(value) || value < 0) {
            input.value = line.weight_g || "";
            return false;
        }
        if (value === line.weight_g) {
            return true;
        }
        // Mientras se pregunta, el campo pierde el foco y vuelve a disparar el guardado:
        // ese segundo intento no hace nada.
        if (this.checkingLine === line.id) {
            return false;
        }
        this.checkingLine = line.id;
        let confirmed;
        try {
            confirmed = await this.confirmOutlier(line, value);
        } finally {
            this.checkingLine = null;
        }
        if (!confirmed) {
            input.value = line.weight_g || "";
            input.focus();
            input.select();
            return false;
        }
        try {
            const result = await this.call("poultry_mobile_set_weight", [[this.state.record.id], line.id, value]);
            line.weight_g = value;
            this.applyCageState(result);
            return true;
        } catch {
            input.value = line.weight_g || "";
            return false;
        }
    }

    onWeightChange(line, ev) {
        return this.commitWeight(line, ev.target);
    }

    async onWeightKeydown(line, ev) {
        if (ev.key !== "Enter") {
            return;
        }
        ev.preventDefault();
        const input = ev.target;
        if (!(await this.commitWeight(line, input))) {
            return;
        }
        const inputs = [...input.closest(".o_pw_cage").querySelectorAll("input.o_pw_weight")];
        const next = inputs[inputs.indexOf(input) + 1];
        if (next) {
            next.focus();
            next.select();
        } else {
            input.blur();
        }
    }

    async addLine() {
        this.state.record = await this.call("poultry_mobile_add_line", [[this.state.record.id], this.state.cageId]);
        this.focusPending = true;
    }

    async closeCage() {
        const result = await this.call("poultry_mobile_close_cage", [[this.state.record.id], this.state.cageId]);
        this.applyCageState(result);
        this.backToRecord();
    }

    // ------------------------------------------------------------------
    // Registrar
    // ------------------------------------------------------------------
    async register() {
        const pending = await this.call("poultry_mobile_pending_cages", [[this.state.record.id]]);
        if (pending.length) {
            this.dialog.add(ConfirmationDialog, {
                title: "Jaulas sin pesar",
                body:
                    `Hay ${pending.length} jaulas sin ningún peso: ${pending.join(", ")}. ` +
                    "Se puede registrar igual: quedan sin pesar en esta pesada.",
                confirmLabel: "Registrar igual",
                cancelLabel: "Seguir pesando",
                confirm: () => this.doRegister(true),
                cancel: () => {},
            });
        } else {
            await this.doRegister(false);
        }
    }

    async doRegister(force) {
        const { id, name } = this.state.record;
        await this.call("action_register", [[id]], {
            force,
            context: { poultry_mobile: true },
        });
        this.notification.add(`Pesada ${name} registrada. Queda a verificar.`, { type: "success" });
        await this.loadList();
    }
}

registry.category("actions").add("poultry_weighing", PoultryWeighing);

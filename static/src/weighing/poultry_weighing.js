import { Component, useState, onWillStart, onPatched } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { scanBarcode } from "@web/core/barcode/barcode_dialog";
import { isBarcodeScannerSupported } from "@web/core/barcode/barcode_video_scanner";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";

const MODEL = "poultry.weight.record";

/**
 * App Avícola Campo, pensada para el celular: inicio → pesadas enviadas a pesar →
 * tarjetas por jaula → pesos de una jaula. La jaula se abre escaneando su QR (cámara
 * del navegador o de la app de Odoo) o escribiendo el código. Solo se escribe el peso:
 * Siguiente/Enter pasa a la ave de abajo. Los avisos se ven en la tarjeta, no mientras
 * se carga.
 */
export class PoultryWeighing extends Component {
    static template = "poultry_management.PoultryWeighing";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.dialog = useService("dialog");
        this.notification = useService("notification");
        this.state = useState({
            screen: "home", // home | list | record | cage
            records: [],
            record: null,
            cageId: null,
            manualCode: "",
            showManual: false,
            busy: false,
        });
        this.scannerSupported = isBarcodeScannerSupported();
        this.focusPending = false;
        onWillStart(() => this.loadRecords());
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
        const pending = this.state.records.filter((rec) => rec.state === "in_progress");
        if (!pending.length) {
            return "Sin pesadas enviadas a pesar";
        }
        const coops = [...new Set(pending.map((rec) => rec.coop))].join(", ");
        return `${pending.length} ${pending.length === 1 ? "pesada en curso" : "pesadas en curso"} · ${coops}`;
    }

    async goHome() {
        await this.loadRecords();
        this.state.screen = "home";
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

    async loadRecords() {
        this.state.records = await this.call("poultry_mobile_list");
        this.state.record = null;
        this.state.cageId = null;
    }

    async loadList() {
        await this.loadRecords();
        this.state.screen = "list";
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
    async commitWeight(line, input) {
        const value = input.value === "" ? 0 : parseFloat(input.value);
        if (Number.isNaN(value) || value < 0) {
            input.value = line.weight_g || "";
            return;
        }
        if (value === line.weight_g) {
            return;
        }
        try {
            const result = await this.call("poultry_mobile_set_weight", [[this.state.record.id], line.id, value]);
            line.weight_g = value;
            this.applyCageState(result);
        } catch {
            input.value = line.weight_g || "";
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
        await this.commitWeight(line, input);
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

    async removeLine() {
        const cage = this.currentCage;
        const last = cage.lines[cage.lines.length - 1];
        if (cage.lines.length <= 1) {
            this.notification.add("La jaula tiene que quedar con al menos una ave.", { type: "warning" });
            return;
        }
        const allWeighed = cage.lines.every((line) => line.weight_g > 0);
        if (allWeighed) {
            this.dialog.add(ConfirmationDialog, {
                title: "Sacar una ave",
                body: `Todas las aves tienen peso. Se borra la ave ${last.bird_no} (${this.fmt(last.weight_g)} g). ¿Continuar?`,
                confirmLabel: "Sacar",
                cancelLabel: "Cancelar",
                confirm: () => this.doRemoveLine(),
                cancel: () => {},
            });
        } else {
            await this.doRemoveLine();
        }
    }

    async doRemoveLine() {
        this.state.record = await this.call("poultry_mobile_remove_line", [[this.state.record.id], this.state.cageId]);
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
        await this.call("action_register", [[this.state.record.id]], {
            force,
            context: { poultry_mobile: true },
        });
        this.notification.add(`Pesada ${this.state.record.name} registrada. Queda a verificar.`, { type: "success" });
        await this.loadList();
    }
}

registry.category("actions").add("poultry_weighing", PoultryWeighing);

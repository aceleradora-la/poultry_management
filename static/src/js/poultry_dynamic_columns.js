/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { ListRenderer } from "@web/views/list/list_renderer";
import { FormRenderer } from "@web/views/form/form_renderer";
import { onPatched, onMounted } from "@odoo/owl";

const LINE_MODEL = "poultry.egg.collection.line";
const COLLECTION_MODEL = "poultry.egg.collection";

// Prefijo por fase + ranura de UdM (1=mayor, 2=intermedia, 3=Huevo) por campo.
// Espeja el reporte impreso: "Inicial CAJÓN", "Bruto MAPLE 30", "Final HUEVO".
const COLUMN_MAP = {
    initial_box: ["Inicial", 1],
    initial_map: ["Inicial", 2],
    initial_egg: ["Inicial", 3],
    final_box: ["Bruto", 1],
    final_map: ["Bruto", 2],
    final_egg: ["Bruto", 3],
    produced_box: ["Final", 1],
    produced_map: ["Final", 2],
    produced_egg: ["Final", 3],
};

function slotName(data, slot) {
    return (data && data[`uom_${slot}_name`]) || "";
}

// Patch ListRenderer: renombra los encabezados de columna en el DOM tras cada
// render (onPatched/onMounted). El header de Odoo 18 no se arma desde el objeto
// devuelto por getColumns, por eso se ajusta directamente en el DOM.
patch(ListRenderer.prototype, {
    setup() {
        super.setup();
        if (this.props.list && this.props.list.resModel === LINE_MODEL) {
            onMounted(() => this._poultryRenameHeaders());
            onPatched(() => this._poultryRenameHeaders());
        }
    },

    _poultryRenameHeaders() {
        if (!this.props.list || this.props.list.resModel !== LINE_MODEL) {
            return;
        }
        const table = this.tableRef && this.tableRef.el;
        if (!table) {
            return;
        }
        const records = this.props.list.records || [];
        if (!records.length) {
            return;
        }
        const data = records[0].data || {};
        const headers = table.querySelectorAll("thead th[data-name]");
        headers.forEach((th) => {
            const mapping = COLUMN_MAP[th.dataset.name];
            if (!mapping) {
                return;
            }
            const [prefix, slot] = mapping;
            const name = slotName(data, slot);
            if (!name) {
                return;
            }
            const titleEl = th.querySelector(".o_column_title") || th.querySelector("span") || th;
            const newText = `${prefix} ${name.toUpperCase()}`;
            if (titleEl.textContent !== newText) {
                titleEl.textContent = newText;
            }
        });
    },
});

// Patch FormRenderer: labels de los totales por UdM en el form de la recolección.
patch(FormRenderer.prototype, {
    setup() {
        super.setup();
        if (this.props.resModel === COLLECTION_MODEL) {
            onMounted(() => this._updateTotalLabels());
            onPatched(() => this._updateTotalLabels());
        }
    },

    _updateTotalLabels() {
        if (this.props.resModel !== COLLECTION_MODEL) {
            return;
        }
        const data = this.props.record && this.props.record.data;
        if (!data) {
            return;
        }
        const fields = {
            total_produced_boxes: 1,
            total_produced_maps: 2,
            total_produced_eggs: 3,
        };
        for (const [field, slot] of Object.entries(fields)) {
            const name = slotName(data, slot);
            if (!name) {
                continue;
            }
            // Un solo form abierto a la vez: consulta segura al documento.
            const label = document.querySelector(`.o_form_view label[for="${field}"]`);
            if (label) {
                label.textContent = `Total Final ${name}`;
            }
        }
    },
});

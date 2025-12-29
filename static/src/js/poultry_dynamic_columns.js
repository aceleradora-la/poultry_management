/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { ListRenderer } from "@web/views/list/list_renderer";
import { FormRenderer } from "@web/views/form/form_renderer";

// Patch para ListRenderer (columnas de la lista)
patch(ListRenderer.prototype, {
    setup() {
        super.setup();
        if (this.props.list && this.props.list.resModel === 'poultry.egg.collection.line') {
            this._updateDynamicColumnHeaders = this._updateDynamicColumnHeaders.bind(this);
            console.log('[Poultry] ListRenderer setup para poultry.egg.collection.line');
        }
    },

    getColumns() {
        const columns = super.getColumns();
        
        if (this.props.list && this.props.list.resModel === 'poultry.egg.collection.line') {
            console.log('[Poultry] getColumns llamado, registros:', this.props.list.records?.length);
            
            // Obtener valores desde el modelo
            let uom1Name = '';
            let uom2Name = '';
            let uom3Name = '';

            if (this.props.list.records && this.props.list.records.length > 0) {
                const firstRecord = this.props.list.records[0];
                uom1Name = firstRecord.data?.uom_1_name || '';
                uom2Name = firstRecord.data?.uom_2_name || '';
                uom3Name = firstRecord.data?.uom_3_name || '';
                
                console.log('[Poultry] Nombres obtenidos del modelo:', { uom1Name, uom2Name, uom3Name });
                
                // Guardar los nombres para usar después en el DOM
                this._uomNames = { uom1Name, uom2Name, uom3Name };
                
                // Actualizar títulos de las columnas
                columns.forEach((column) => {
                    if (column.name === 'initial_box' && uom1Name) {
                        column.title = `${uom1Name} Inicial`;
                        console.log('[Poultry] Actualizado initial_box:', column.title);
                    } else if (column.name === 'initial_map' && uom2Name) {
                        column.title = `${uom2Name} Inicial`;
                        console.log('[Poultry] Actualizado initial_map:', column.title);
                    } else if (column.name === 'initial_egg' && uom3Name) {
                        column.title = `${uom3Name} Inicial`;
                        console.log('[Poultry] Actualizado initial_egg:', column.title);
                    } else if (column.name === 'final_box' && uom1Name) {
                        column.title = `${uom1Name} Final`;
                        console.log('[Poultry] Actualizado final_box:', column.title);
                    } else if (column.name === 'final_map' && uom2Name) {
                        column.title = `${uom2Name} Final`;
                        console.log('[Poultry] Actualizado final_map:', column.title);
                    } else if (column.name === 'final_egg' && uom3Name) {
                        column.title = `${uom3Name} Final`;
                        console.log('[Poultry] Actualizado final_egg:', column.title);
                    }
                });
            }
        }
        
        return columns;
    },

    _updateDynamicColumnHeaders() {
        if (!this.el) {
            console.log('[Poultry] No hay elemento el');
            return;
        }

        // Intentar múltiples selectores para encontrar la tabla
        const table = this.el.querySelector('table.o_list_table') || 
                     this.el.querySelector('table') ||
                     document.querySelector('table.o_list_table');
        
        if (!table) {
            console.log('[Poultry] No se encontró la tabla');
            return;
        }

        // Buscar headers de múltiples formas
        let headers = table.querySelectorAll('thead th');
        if (!headers.length) {
            headers = table.querySelectorAll('th');
        }
        if (!headers.length) {
            headers = table.querySelectorAll('.o_list_table thead th');
        }
        
        if (!headers.length) {
            console.log('[Poultry] No se encontraron headers, total encontrados:', headers.length);
            return;
        }

        console.log('[Poultry] Headers encontrados:', headers.length);

        // Usar los nombres guardados o intentar obtenerlos del modelo
        let uom1Name = this._uomNames?.uom1Name || '';
        let uom2Name = this._uomNames?.uom2Name || '';
        let uom3Name = this._uomNames?.uom3Name || '';

        if (!uom1Name && this.props.list && this.props.list.records && this.props.list.records.length > 0) {
            const firstRecord = this.props.list.records[0];
            uom1Name = firstRecord.data?.uom_1_name || '';
            uom2Name = firstRecord.data?.uom_2_name || '';
            uom3Name = firstRecord.data?.uom_3_name || '';
            console.log('[Poultry] Nombres obtenidos del modelo en _updateDynamicColumnHeaders:', { uom1Name, uom2Name, uom3Name });
        }

        if (!uom1Name) {
            console.log('[Poultry] No hay nombres UoM disponibles');
            return;
        }

        // Actualizar headers en el DOM directamente
        headers.forEach((header, index) => {
            // Intentar múltiples formas de obtener el nombre del campo
            let fieldName = header.getAttribute('data-name') || 
                           header.getAttribute('name') ||
                           header.querySelector('[data-name]')?.getAttribute('data-name') ||
                           header.closest('th')?.getAttribute('data-name');
            
            // Si no encontramos el nombre, intentar desde el contenido o el índice
            if (!fieldName) {
                // Buscar en los spans dentro del header
                const spans = header.querySelectorAll('span');
                spans.forEach(span => {
                    const name = span.getAttribute('data-name') || span.getAttribute('name');
                    if (name) fieldName = name;
                });
            }

            // Si aún no tenemos el nombre, intentar desde el texto actual
            if (!fieldName) {
                const currentText = header.textContent?.trim().toLowerCase();
                if (currentText.includes('initial box') || currentText.includes('initial_box')) {
                    fieldName = 'initial_box';
                } else if (currentText.includes('initial map') || currentText.includes('initial_map')) {
                    fieldName = 'initial_map';
                } else if (currentText.includes('initial egg') || currentText.includes('initial_egg')) {
                    fieldName = 'initial_egg';
                } else if (currentText.includes('final box') || currentText.includes('final_box')) {
                    fieldName = 'final_box';
                } else if (currentText.includes('final map') || currentText.includes('final_map')) {
                    fieldName = 'final_map';
                } else if (currentText.includes('final egg') || currentText.includes('final_egg')) {
                    fieldName = 'final_egg';
                }
            }

            if (!fieldName) {
                console.log(`[Poultry] Header ${index}: No se encontró fieldName, texto actual:`, header.textContent?.trim());
                return;
            }

            // Buscar el elemento de texto dentro del header
            let headerText = header.querySelector('.o_column_title') || 
                           header.querySelector('span.o_column_title') ||
                           header.querySelector('span[title]') ||
                           header.querySelector('span') ||
                           header.querySelector('div') ||
                           header;

            const currentText = headerText.textContent?.trim();
            let newText = '';

            if (fieldName === 'initial_box' && uom1Name) {
                newText = `${uom1Name} Inicial`;
            } else if (fieldName === 'initial_map' && uom2Name) {
                newText = `${uom2Name} Inicial`;
            } else if (fieldName === 'initial_egg' && uom3Name) {
                newText = `${uom3Name} Inicial`;
            } else if (fieldName === 'final_box' && uom1Name) {
                newText = `${uom1Name} Final`;
            } else if (fieldName === 'final_map' && uom2Name) {
                newText = `${uom2Name} Final`;
            } else if (fieldName === 'final_egg' && uom3Name) {
                newText = `${uom3Name} Final`;
            }

            if (newText && currentText !== newText) {
                headerText.textContent = newText;
                // También actualizar el atributo title si existe
                if (headerText.hasAttribute('title')) {
                    headerText.setAttribute('title', newText);
                }
                console.log(`[Poultry] DOM actualizado: ${fieldName} = "${newText}" (antes: "${currentText}")`);
            }
        });
    },

    onMounted() {
        super.onMounted();
        if (this.props.list && this.props.list.resModel === 'poultry.egg.collection.line') {
            console.log('[Poultry] onMounted para lista');
            // Usar requestAnimationFrame para asegurar que el DOM esté listo
            requestAnimationFrame(() => {
                setTimeout(() => this._updateDynamicColumnHeaders(), 100);
                setTimeout(() => this._updateDynamicColumnHeaders(), 500);
                setTimeout(() => this._updateDynamicColumnHeaders(), 1000);
                setTimeout(() => this._updateDynamicColumnHeaders(), 2000);
            });
        }
    },

    onWillUpdateProps(nextProps) {
        super.onWillUpdateProps(nextProps);
        if (nextProps.list && nextProps.list.resModel === 'poultry.egg.collection.line') {
            console.log('[Poultry] onWillUpdateProps para lista');
            requestAnimationFrame(() => {
                setTimeout(() => this._updateDynamicColumnHeaders(), 100);
                setTimeout(() => this._updateDynamicColumnHeaders(), 500);
            });
        }
    },
});

// Patch para FormRenderer (labels de totales)
patch(FormRenderer.prototype, {
    setup() {
        super.setup();
        if (this.props.resModel === 'poultry.egg.collection') {
            this._updateTotalLabels = this._updateTotalLabels.bind(this);
            console.log('[Poultry] FormRenderer setup para poultry.egg.collection');
        }
    },

    _updateTotalLabels() {
        const form = this.el?.querySelector('.o_form_view');
        if (!form) {
            console.log('[Poultry] No se encontró el formulario');
            return;
        }

        const record = this.props.record;
        if (!record || !record.data) {
            console.log('[Poultry] No hay record o data');
            return;
        }

        const uom1Name = record.data.uom_1_name || '';
        const uom2Name = record.data.uom_2_name || '';
        const uom3Name = record.data.uom_3_name || '';

        console.log('[Poultry] _updateTotalLabels - Nombres:', { uom1Name, uom2Name, uom3Name });

        // Actualizar labels de totales iniciales
        const totalInitialBoxesLabel = form.querySelector('label[for="total_initial_boxes"]');
        if (totalInitialBoxesLabel && uom1Name) {
            totalInitialBoxesLabel.textContent = `Total Inicial ${uom1Name}`;
            console.log('[Poultry] Actualizado label total_initial_boxes');
        }
        const totalInitialMapsLabel = form.querySelector('label[for="total_initial_maps"]');
        if (totalInitialMapsLabel && uom2Name) {
            totalInitialMapsLabel.textContent = `Total Inicial ${uom2Name}`;
        }
        const totalInitialEggsLabel = form.querySelector('label[for="total_initial_eggs"]');
        if (totalInitialEggsLabel && uom3Name) {
            totalInitialEggsLabel.textContent = `Total Inicial ${uom3Name}`;
        }

        // Actualizar labels de totales finales
        const totalFinalBoxesLabel = form.querySelector('label[for="total_final_boxes"]');
        if (totalFinalBoxesLabel && uom1Name) {
            totalFinalBoxesLabel.textContent = `Total Final ${uom1Name}`;
        }
        const totalFinalMapsLabel = form.querySelector('label[for="total_final_maps"]');
        if (totalFinalMapsLabel && uom2Name) {
            totalFinalMapsLabel.textContent = `Total Final ${uom2Name}`;
        }
        const totalFinalEggsLabel = form.querySelector('label[for="total_final_eggs"]');
        if (totalFinalEggsLabel && uom3Name) {
            totalFinalEggsLabel.textContent = `Total Final ${uom3Name}`;
        }

        // Actualizar labels de totales producidos
        const totalProducedBoxesLabel = form.querySelector('label[for="total_produced_boxes"]');
        if (totalProducedBoxesLabel && uom1Name) {
            totalProducedBoxesLabel.textContent = `Total Producido ${uom1Name}`;
        }
        const totalProducedMapsLabel = form.querySelector('label[for="total_produced_maps"]');
        if (totalProducedMapsLabel && uom2Name) {
            totalProducedMapsLabel.textContent = `Total Producido ${uom2Name}`;
        }
        const totalProducedEggsLabel = form.querySelector('label[for="total_produced_eggs"]');
        if (totalProducedEggsLabel && uom3Name) {
            totalProducedEggsLabel.textContent = `Total Producido ${uom3Name}`;
        }
    },

    onMounted() {
        super.onMounted();
        if (this.props.resModel === 'poultry.egg.collection') {
            console.log('[Poultry] onMounted para formulario');
            requestAnimationFrame(() => {
                setTimeout(() => this._updateTotalLabels(), 100);
                setTimeout(() => this._updateTotalLabels(), 500);
            });
        }
    },

    onWillUpdateProps(nextProps) {
        super.onWillUpdateProps(nextProps);
        if (nextProps.resModel === 'poultry.egg.collection') {
            console.log('[Poultry] onWillUpdateProps para formulario');
            requestAnimationFrame(() => {
                setTimeout(() => this._updateTotalLabels(), 100);
            });
        }
    },
});

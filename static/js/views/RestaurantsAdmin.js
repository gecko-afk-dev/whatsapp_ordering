/**
 * RestaurantsAdmin.js — Direction B Fleet Management Table
 *
 * Features:
 *  - Pitch-black (#0A0A0A) Stripe/Vercel table aesthetic
 *  - Saffron row-hover glow (inset border via box-shadow)
 *  - Suspension kill-switch with confirmation bottom sheet
 *  - Add / Edit restaurant modal (dark theme)
 *  - Status badge, commission tier, city column
 */
import { ref, onMounted } from 'https://unpkg.com/vue@3/dist/vue.esm-browser.js';
import { api } from '../api.js';

export default {
    name: 'RestaurantsAdmin',
    template: `
        <div class="space-y-6 animate-fade-in">

            <!-- ════ HEADER ════ -->
            <div class="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
                <div>
                    <h2 class="text-2xl font-black text-slate-100">Restaurant Fleet</h2>
                    <p class="text-sm text-slate-600 mt-0.5">{{ restaurants.length }} restaurant{{ restaurants.length !== 1 ? 's' : '' }} registered</p>
                </div>
                <button @click="openModal" id="restaurants-add-btn"
                        class="btn btn-saffron text-sm px-5 h-10 shrink-0">
                    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M12 4v16m8-8H4"/>
                    </svg>
                    Add Restaurant
                </button>
            </div>

            <!-- Loading skeleton -->
            <div v-if="loading" class="space-y-2">
                <div v-for="i in 5" :key="i" class="skeleton h-16 rounded-xl"></div>
            </div>

            <!-- ════ DESKTOP TABLE ════ -->
            <div v-else class="hidden md:block overflow-x-auto rounded-2xl border border-superadmin-border">
                <table class="table-dark" style="background: var(--superadmin-bg)">
                    <thead>
                        <tr>
                            <th>Restaurant</th>
                            <th>City</th>
                            <th>Contact</th>
                            <th>Commission</th>
                            <th>Vol. (30d)</th>
                            <th>Billing Tier</th>
                            <th>Status</th>
                            <th class="text-right">Actions</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr v-if="restaurants.length === 0">
                            <td colspan="8" class="text-center text-slate-700 py-10 text-sm italic">No restaurants found.</td>
                        </tr>
                        <tr v-for="r in restaurants" :key="r.id"
                            class="group"
                            style="background: var(--superadmin-bg); border-bottom-color: var(--superadmin-border)">
                            <td>
                                <div class="font-bold text-slate-200 text-sm">{{ r.name }}</div>
                                <div class="text-xs text-slate-700">ID #{{ r.id }}</div>
                            </td>
                            <td class="text-slate-500 text-sm">{{ r.city || '—' }}</td>
                            <td class="text-slate-500 text-xs">{{ r.contact_email }}</td>
                            <td>
                                <span class="badge badge-slate">{{ ((r.commission_rate || 0) * 100).toFixed(0) }}%</span>
                            </td>
                            <td class="text-slate-500 text-sm font-semibold">{{ r.orders_30d ?? '—' }}</td>
                            <td>
                                <span class="badge" :class="billingBadge(r.commission_rate)">{{ billingTier(r.commission_rate) }}</span>
                            </td>
                            <td>
                                <span class="badge" :class="r.status === 'active' ? 'badge-emerald' : 'badge-harissa'">
                                    {{ r.status === 'active' ? '● Active' : '✕ Suspended' }}
                                </span>
                            </td>
                            <td class="text-right">
                                <div class="flex items-center justify-end gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
                                    <button @click="editRestaurant(r)"
                                            :id="'restaurant-edit-' + r.id"
                                            class="btn btn-ghost text-xs px-3 h-8">Edit</button>
                                    <button v-if="r.status === 'active'"
                                            @click="promptSuspend(r)"
                                            :id="'restaurant-suspend-' + r.id"
                                            class="btn btn-danger text-xs px-3 h-8">Suspend</button>
                                    <button v-else
                                            @click="activate(r.id)"
                                            :id="'restaurant-activate-' + r.id"
                                            class="btn text-xs px-3 h-8 bg-emerald/10 text-emerald border border-emerald/30 hover:bg-emerald/20">Activate</button>
                                </div>
                            </td>
                        </tr>
                    </tbody>
                </table>
            </div>

            <!-- ════ MOBILE CARD LIST ════ -->
            <div class="md:hidden space-y-3">
                <div v-if="restaurants.length === 0" class="card-dark p-8 text-center text-slate-600 text-sm">No restaurants found.</div>
                <div v-for="r in restaurants" :key="r.id"
                     class="card-superadmin p-4 hover-glow-saffron transition-all">
                    <div class="flex items-start justify-between mb-3">
                        <div>
                            <div class="font-black text-slate-100">{{ r.name }}</div>
                            <div class="text-xs text-slate-600 mt-0.5">{{ r.contact_email }}</div>
                        </div>
                        <span class="badge" :class="r.status === 'active' ? 'badge-emerald' : 'badge-harissa'">
                            {{ r.status === 'active' ? 'Active' : 'Suspended' }}
                        </span>
                    </div>
                    <div class="flex gap-2">
                        <button @click="editRestaurant(r)" class="btn btn-ghost text-xs h-9 flex-1">Edit</button>
                        <button v-if="r.status === 'active'" @click="promptSuspend(r)" class="btn btn-danger text-xs h-9 flex-1">Suspend</button>
                        <button v-else @click="activate(r.id)" class="btn text-xs h-9 flex-1 bg-emerald/10 text-emerald border border-emerald/30">Activate</button>
                    </div>
                </div>
            </div>

            <!-- ════ SUSPENSION KILL-SWITCH CONFIRMATION SHEET ════ -->
            <template v-if="suspendTarget">
                <div class="bottom-sheet-backdrop" @click="suspendTarget = null"></div>
                <div class="bottom-sheet">
                    <div class="w-10 h-1 bg-slate-700 rounded-full mx-auto mb-5"></div>
                    <div class="flex items-center gap-3 mb-4">
                        <div class="w-10 h-10 rounded-xl bg-harissa/15 flex items-center justify-center text-harissa text-xl shrink-0">⚠️</div>
                        <div>
                            <h3 class="text-lg font-black text-slate-100">Suspend Restaurant?</h3>
                            <p class="text-xs text-slate-500">{{ suspendTarget.name }}</p>
                        </div>
                    </div>
                    <p class="text-sm text-slate-400 mb-2">
                        This will <span class="text-harissa font-bold">immediately invalidate</span> the restaurant's webhook config.
                        Customers messaging them will receive a maintenance notification.
                    </p>
                    <p class="text-xs text-slate-600 mb-6 font-mono bg-superadmin-bg border border-superadmin-border rounded-lg px-3 py-2">
                        "Ce restaurant est temporairement en maintenance…"
                    </p>
                    <div class="flex gap-3">
                        <button @click="suspendTarget = null" id="suspend-cancel-btn" class="btn btn-ghost flex-1">Cancel</button>
                        <button @click="confirmSuspend" id="suspend-confirm-btn" class="btn btn-danger flex-1 font-bold">Yes, Suspend</button>
                    </div>
                </div>
            </template>

            <!-- ════ ADD / EDIT RESTAURANT MODAL ════ -->
            <template v-if="showCreate">
                <div class="fixed inset-0 bg-black/75 backdrop-blur-sm flex items-center justify-center p-4 z-50">
                    <div class="w-full max-w-lg max-h-[90vh] overflow-y-auto rounded-2xl border border-superadmin-border shadow-2xl"
                         style="background: var(--superadmin-bg)">
                        <div class="px-6 pt-6 pb-4 border-b border-superadmin-border">
                            <h3 class="text-lg font-black text-slate-100">
                                {{ editingId ? 'Edit Restaurant' : 'Register New Restaurant' }}
                            </h3>
                        </div>

                        <div class="px-6 py-5 space-y-4">
                            <div class="grid grid-cols-2 gap-4">
                                <div class="col-span-2">
                                    <label class="block text-xs font-bold text-slate-600 uppercase tracking-wider mb-1.5">Restaurant Name *</label>
                                    <input v-model="form.name" id="form-name" type="text" class="input-dark" placeholder="Pizzeria Al-Andalus">
                                </div>
                                <div>
                                    <label class="block text-xs font-bold text-slate-600 uppercase tracking-wider mb-1.5">Contact Email</label>
                                    <input v-model="form.contact_email" id="form-email" type="email" class="input-dark" placeholder="owner@example.com">
                                </div>
                                <div>
                                    <label class="block text-xs font-bold text-slate-600 uppercase tracking-wider mb-1.5">City</label>
                                    <input v-model="form.city" id="form-city" type="text" class="input-dark" placeholder="Casablanca">
                                </div>
                                <div class="col-span-2">
                                    <label class="block text-xs font-bold text-slate-600 uppercase tracking-wider mb-1.5">WhatsApp Phone Number</label>
                                    <input v-model="form.wa_phone_number" id="form-phone" type="text" class="input-dark" placeholder="+212600000000">
                                </div>
                                <div class="col-span-2">
                                    <label class="block text-xs font-bold text-slate-600 uppercase tracking-wider mb-1.5">Meta Phone Number ID</label>
                                    <input v-model="form.phone_number_id" id="form-phone-id" type="text" class="input-dark">
                                </div>
                                <div class="col-span-2">
                                    <label class="block text-xs font-bold text-slate-600 uppercase tracking-wider mb-1.5">Permanent API Token</label>
                                    <textarea v-model="form.api_token" id="form-api-token" class="input-dark h-16 resize-none" autocomplete="off"></textarea>
                                </div>
                                <div class="col-span-2">
                                    <label class="block text-xs font-bold text-slate-600 uppercase tracking-wider mb-1.5">Owner WhatsApp ID (manager notifications)</label>
                                    <input v-model="form.owner_wa_id" id="form-owner-wa" type="text" class="input-dark" placeholder="212611223344">
                                </div>
                                <div>
                                    <label class="block text-xs font-bold text-slate-600 uppercase tracking-wider mb-1.5">Commission Rate (0–1)</label>
                                    <input v-model.number="form.commission_rate" id="form-commission" type="number" step="0.01" min="0" max="1" class="input-dark">
                                </div>
                                <div>
                                    <label class="block text-xs font-bold text-slate-600 uppercase tracking-wider mb-1.5">Cuisine Type</label>
                                    <input v-model="form.cuisine_type" id="form-cuisine" type="text" class="input-dark" placeholder="Fast Food">
                                </div>
                            </div>

                            <div v-if="error" class="p-3 rounded-xl bg-harissa/10 border border-harissa/30 text-harissa text-sm">{{ error }}</div>
                        </div>

                        <div class="px-6 pb-6 flex gap-3 border-t border-superadmin-border pt-4">
                            <button @click="showCreate = false" id="modal-cancel-btn" class="btn btn-ghost flex-1">Cancel</button>
                            <button @click="save" id="modal-save-btn" class="btn btn-saffron flex-1">
                                {{ editingId ? 'Save Changes' : 'Create Restaurant' }}
                            </button>
                        </div>
                    </div>
                </div>
            </template>
        </div>
    `,

    setup() {
        const restaurants  = ref([]);
        const loading      = ref(true);
        const showCreate   = ref(false);
        const error        = ref('');
        const suspendTarget = ref(null);

        const emptyForm = () => ({
            name: '', wa_phone_number: '', api_token: '', phone_number_id: '',
            owner_wa_id: '', cuisine_type: '', contact_email: '',
            city: '', commission_rate: 0.20,
        });

        const form      = ref(emptyForm());
        const editingId = ref(null);

        // ── Billing tier helpers ──────────────────────────────────────────
        const billingTier = (rate) => {
            if (rate >= 0.25) return 'Premium';
            if (rate >= 0.15) return 'Growth';
            return 'Starter';
        };
        const billingBadge = (rate) => {
            if (rate >= 0.25) return 'badge-saffron';
            if (rate >= 0.15) return 'badge-berry';
            return 'badge-slate';
        };

        // ── CRUD ──────────────────────────────────────────────────────────
        const loadRestaurants = async () => {
            loading.value = true;
            try {
                const res = await api.get('/admin/restaurants');
                restaurants.value = res.data;
            } catch (err) {
                console.error('[RestaurantsAdmin] load error', err);
            } finally {
                loading.value = false;
            }
        };

        const openModal = () => {
            editingId.value = null;
            form.value      = emptyForm();
            error.value     = '';
            showCreate.value = true;
        };

        const editRestaurant = (r) => {
            editingId.value = r.id;
            form.value      = {
                name: r.name || '',              wa_phone_number: r.wa_phone_number || '',
                api_token: r.api_token || '',    phone_number_id: r.phone_number_id || '',
                owner_wa_id: r.owner_wa_id || '', cuisine_type: r.cuisine_type || '',
                contact_email: r.contact_email || '', city: r.city || '',
                commission_rate: r.commission_rate || 0.20,
            };
            error.value      = '';
            showCreate.value = true;
        };

        const save = async () => {
            error.value = '';
            if (!form.value.name.trim()) { error.value = 'Restaurant name is required.'; return; }
            try {
                if (editingId.value) {
                    await api.put(`/admin/restaurants/${editingId.value}`, form.value);
                } else {
                    await api.post('/admin/restaurants', form.value);
                }
                showCreate.value = false;
                editingId.value  = null;
                form.value       = emptyForm();
                await loadRestaurants();
            } catch (err) {
                error.value = err.response?.data?.detail || 'Failed to save.';
            }
        };

        // ── Suspension kill-switch ────────────────────────────────────────
        const promptSuspend = (r) => { suspendTarget.value = r; };
        const confirmSuspend = async () => {
            if (!suspendTarget.value) return;
            const id = suspendTarget.value.id;
            suspendTarget.value = null;
            try {
                await api.post(`/admin/restaurants/${id}/suspend`);
                await loadRestaurants();
            } catch (err) { console.error('[RestaurantsAdmin] suspend error', err); }
        };

        const activate = async (id) => {
            try {
                await api.post(`/admin/restaurants/${id}/activate`);
                await loadRestaurants();
            } catch (err) { console.error('[RestaurantsAdmin] activate error', err); }
        };

        onMounted(loadRestaurants);

        return {
            restaurants, loading, showCreate, error, form, editingId,
            suspendTarget,
            openModal, editRestaurant, save,
            promptSuspend, confirmSuspend, activate,
            billingTier, billingBadge,
        };
    }
};

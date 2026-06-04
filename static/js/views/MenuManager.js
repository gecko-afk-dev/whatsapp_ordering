/**
 * MenuManager.js — Direction B redesign
 *
 * Features:
 *  - Category filter tabs (ALL + dynamic categories)
 *  - Dense scannable table on Tablet/Desktop
 *  - Card list on Mobile
 *  - Inline price editor (numeric input on pencil click)
 *  - Stock toggle bottom-sheet confirmation (Heuristic #5)
 *  - Out-of-stock rows/cards dimmed to 60% opacity
 *  - Add Category & Add Item modals (dark-theme)
 */
import { ref, computed, onMounted } from 'https://unpkg.com/vue@3/dist/vue.esm-browser.js';
import { api } from '../api.js';

export default {
    name: 'MenuManager',
    template: `
        <div class="space-y-6 animate-fade-in">

            <!-- ════════ PAGE HEADER ════════ -->
            <div class="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
                <div>
                    <h2 class="text-2xl font-black text-slate-100">Menu Management</h2>
                    <p class="text-sm text-slate-500 mt-0.5">Manage items, prices, and availability</p>
                </div>
                <button @click="openAddCategoryModal" id="menu-add-category-btn"
                        class="btn btn-saffron text-sm px-5 h-10 shrink-0">
                    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M12 4v16m8-8H4"/>
                    </svg>
                    Add Category
                </button>
            </div>

            <!-- ════════ CATEGORY FILTER TABS ════════ -->
            <div class="flex gap-2 overflow-x-auto pb-1 scrollbar-hide">
                <button @click="activeCategory = null" id="menu-tab-all"
                        class="shrink-0 px-4 py-2 rounded-full text-xs font-bold transition-all"
                        :class="activeCategory === null
                            ? 'bg-saffron text-black shadow-[0_0_12px_rgba(245,158,11,0.4)]'
                            : 'bg-surface text-slate-400 hover:text-slate-200 border border-white/[0.07]'">
                    ALL
                </button>
                <button v-for="cat in categories" :key="cat.id"
                        @click="activeCategory = cat.id"
                        :id="'menu-tab-cat-' + cat.id"
                        class="shrink-0 px-4 py-2 rounded-full text-xs font-bold transition-all"
                        :class="activeCategory === cat.id
                            ? 'bg-saffron text-black shadow-[0_0_12px_rgba(245,158,11,0.4)]'
                            : 'bg-surface text-slate-400 hover:text-slate-200 border border-white/[0.07]'">
                    {{ cat.name_en }}
                </button>
            </div>

            <!-- ════════ LOADING ════════ -->
            <div v-if="loading" class="space-y-3">
                <div v-for="i in 3" :key="i" class="skeleton h-14 w-full rounded-xl"></div>
            </div>

            <!-- ════════ EMPTY STATE ════════ -->
            <div v-else-if="categories.length === 0"
                 class="card-dark p-12 text-center">
                <div class="w-16 h-16 rounded-2xl bg-surface flex items-center justify-center mx-auto mb-4 border border-white/[0.07]">
                    <svg class="w-8 h-8 text-slate-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2"/>
                    </svg>
                </div>
                <p class="text-slate-500 font-semibold">Your menu is empty — add a category to get started.</p>
            </div>

            <!-- ════════ CATEGORY BLOCKS ════════ -->
            <div v-else class="space-y-6">
                <div v-for="cat in filteredCategories" :key="cat.id" class="card-dark overflow-hidden">

                    <!-- Category header -->
                    <div class="px-5 py-4 border-b border-white/[0.06] flex justify-between items-center bg-surface/40">
                        <div>
                            <h3 class="text-base font-black text-slate-100">{{ cat.name_en }}</h3>
                            <span class="text-xs text-slate-600 font-medium">{{ cat.name_fr }} / <span dir="auto" class="font-cairo">{{ cat.name_ar }}</span></span>
                        </div>
                        <div class="flex items-center gap-3">
                            <button @click="openAddItemModal(cat.id)" :id="'menu-add-item-' + cat.id"
                                    class="text-xs font-bold text-saffron hover:text-saffron-light transition-colors">
                                + Add Item
                            </button>
                            <button @click="deleteCategory(cat.id)" :id="'menu-del-cat-' + cat.id"
                                    class="text-xs font-bold text-harissa/70 hover:text-harissa transition-colors">
                                Delete
                            </button>
                        </div>
                    </div>

                    <!-- ── DESKTOP: dense table ── -->
                    <div class="hidden md:block overflow-x-auto">
                        <table class="table-dark">
                            <thead>
                                <tr>
                                    <th>Item</th>
                                    <th>Price (MAD)</th>
                                    <th>Status</th>
                                    <th class="text-right">Actions</th>
                                </tr>
                            </thead>
                            <tbody>
                                <tr v-if="!cat.items || cat.items.length === 0">
                                    <td colspan="4" class="text-center text-slate-700 italic text-xs py-6">No items — click "+ Add Item" to start.</td>
                                </tr>
                                <tr v-for="item in cat.items" :key="item.id"
                                    :class="!item.is_available ? 'opacity-60' : ''"
                                    class="group">
                                    <!-- Name -->
                                    <td>
                                        <div dir="auto" class="font-semibold text-slate-200 font-cairo">{{ item.name_en }}</div>
                                        <div class="text-xs text-slate-600">{{ item.name_fr }}</div>
                                    </td>
                                    <!-- Price — inline edit -->
                                    <td class="w-32">
                                        <div v-if="editingPriceId === item.id" class="flex items-center gap-1.5">
                                            <input type="number" inputmode="decimal" pattern="[0-9]*"
                                                   v-model.number="editingPriceValue"
                                                   :id="'menu-price-input-' + item.id"
                                                   class="input-dark w-24 py-1.5 px-2 text-sm"
                                                   @keyup.enter="savePrice(item)"
                                                   @keyup.esc="editingPriceId = null">
                                            <button @click="savePrice(item)" class="text-saffron text-xs font-bold">✓</button>
                                        </div>
                                        <div v-else class="flex items-center gap-2">
                                            <span class="text-slate-300 font-semibold text-sm">{{ item.price }}</span>
                                            <button @click="startEditPrice(item)"
                                                    :id="'menu-edit-price-' + item.id"
                                                    class="opacity-0 group-hover:opacity-100 text-slate-600 hover:text-saffron transition-all text-xs">
                                                ✎
                                            </button>
                                        </div>
                                    </td>
                                    <!-- Availability toggle -->
                                    <td class="w-28">
                                        <button @click="promptStockToggle(item)"
                                                :id="'menu-stock-toggle-' + item.id"
                                                class="badge transition-all"
                                                :class="item.is_available ? 'badge-emerald' : 'badge-harissa'">
                                            {{ item.is_available ? '● In Stock' : '✕ Sold Out' }}
                                        </button>
                                    </td>
                                    <!-- Delete -->
                                    <td class="text-right w-16">
                                        <button @click="deleteItem(item.id)"
                                                :id="'menu-del-item-' + item.id"
                                                class="text-slate-700 hover:text-harissa transition-colors opacity-0 group-hover:opacity-100">
                                            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/>
                                            </svg>
                                        </button>
                                    </td>
                                </tr>
                            </tbody>
                        </table>
                    </div>

                    <!-- ── MOBILE: card list ── -->
                    <div class="md:hidden divide-y divide-white/[0.05]">
                        <div v-if="!cat.items || cat.items.length === 0"
                             class="px-5 py-4 text-sm text-slate-700 italic">No items.</div>
                        <div v-for="item in cat.items" :key="item.id"
                             class="px-5 py-4 flex items-center justify-between gap-3"
                             :class="!item.is_available ? 'opacity-60' : ''">
                            <div class="flex-1 min-w-0">
                                <div dir="auto" class="font-semibold text-slate-200 text-sm truncate font-cairo">{{ item.name_en }}</div>
                                <div class="text-xs text-slate-500">{{ item.price }} MAD</div>
                            </div>
                            <div class="flex items-center gap-3 shrink-0">
                                <button @click="promptStockToggle(item)"
                                        class="badge text-xs"
                                        :class="item.is_available ? 'badge-emerald' : 'badge-harissa'">
                                    {{ item.is_available ? 'In Stock' : 'Out' }}
                                </button>
                                <button @click="deleteItem(item.id)" class="text-slate-700 hover:text-harissa transition-colors">
                                    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/>
                                    </svg>
                                </button>
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            <!-- ════════ STOCK TOGGLE BOTTOM SHEET ════════ -->
            <template v-if="stockConfirmItem">
                <div class="bottom-sheet-backdrop" @click="stockConfirmItem = null"></div>
                <div class="bottom-sheet">
                    <div class="w-10 h-1 bg-slate-700 rounded-full mx-auto mb-5"></div>
                    <h3 class="text-lg font-black text-slate-100 mb-1">
                        {{ stockConfirmItem.is_available ? 'Mark as Sold Out?' : 'Mark as In Stock?' }}
                    </h3>
                    <p class="text-sm text-slate-400 mb-6">
                        <span class="font-bold text-slate-200">{{ stockConfirmItem.name_en }}</span>
                        will be {{ stockConfirmItem.is_available ? 'hidden from the WhatsApp Flow immediately.' : 'visible to customers again.' }}
                    </p>
                    <div class="flex gap-3">
                        <button @click="stockConfirmItem = null" id="stock-cancel-btn" class="btn btn-ghost flex-1">Cancel</button>
                        <button @click="confirmStockToggle" id="stock-confirm-btn"
                                class="btn flex-1 font-bold"
                                :class="stockConfirmItem.is_available ? 'btn-danger' : 'btn-saffron'">
                            {{ stockConfirmItem.is_available ? 'Yes, Sell Out' : 'Yes, Restore' }}
                        </button>
                    </div>
                </div>
            </template>

            <!-- ════════ ADD CATEGORY MODAL ════════ -->
            <template v-if="showAddCategory">
                <div class="fixed inset-0 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4 z-50">
                    <div class="card-dark w-full max-w-md p-6 shadow-2xl">
                        <h3 class="text-lg font-black text-slate-100 mb-5">New Category</h3>
                        <div class="space-y-4">
                            <div>
                                <label class="block text-xs font-bold text-slate-500 uppercase tracking-wider mb-1.5">Name (EN)</label>
                                <input v-model="catForm.name_en" id="cat-name-en" type="text" class="input-dark" placeholder="Burgers">
                            </div>
                            <div>
                                <label class="block text-xs font-bold text-slate-500 uppercase tracking-wider mb-1.5">Name (FR)</label>
                                <input v-model="catForm.name_fr" id="cat-name-fr" type="text" class="input-dark" placeholder="Burgers">
                            </div>
                            <div>
                                <label class="block text-xs font-bold text-slate-500 uppercase tracking-wider mb-1.5">Name (AR)</label>
                                <input v-model="catForm.name_ar" id="cat-name-ar" type="text" dir="rtl" class="input-dark font-cairo" placeholder="برغر">
                            </div>
                        </div>
                        <div v-if="modalError" class="mt-4 p-3 rounded-lg bg-harissa/10 border border-harissa/30 text-harissa text-sm">{{ modalError }}</div>
                        <div class="flex gap-3 mt-6">
                            <button @click="showAddCategory = false" class="btn btn-ghost flex-1">Cancel</button>
                            <button @click="saveCategory" id="cat-save-btn" class="btn btn-saffron flex-1">Create</button>
                        </div>
                    </div>
                </div>
            </template>

            <!-- ════════ ADD ITEM MODAL ════════ -->
            <template v-if="showAddItem">
                <div class="fixed inset-0 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4 z-50">
                    <div class="card-dark w-full max-w-md max-h-[90vh] overflow-y-auto p-6 shadow-2xl">
                        <h3 class="text-lg font-black text-slate-100 mb-5">New Menu Item</h3>
                        <div class="space-y-4">
                            <div>
                                <label class="block text-xs font-bold text-slate-500 uppercase tracking-wider mb-1.5">Name (EN)</label>
                                <input v-model="itemForm.name_en" id="item-name-en" type="text" class="input-dark" placeholder="Classic Burger">
                            </div>
                            <div>
                                <label class="block text-xs font-bold text-slate-500 uppercase tracking-wider mb-1.5">Name (FR)</label>
                                <input v-model="itemForm.name_fr" id="item-name-fr" type="text" class="input-dark" placeholder="Burger Classique">
                            </div>
                            <div>
                                <label class="block text-xs font-bold text-slate-500 uppercase tracking-wider mb-1.5">Name (AR)</label>
                                <input v-model="itemForm.name_ar" id="item-name-ar" type="text" dir="rtl" class="input-dark font-cairo" placeholder="برغر كلاسيك">
                            </div>
                            <div>
                                <label class="block text-xs font-bold text-slate-500 uppercase tracking-wider mb-1.5">Price (MAD)</label>
                                <input v-model.number="itemForm.price" id="item-price" type="number" inputmode="decimal" class="input-dark" placeholder="45">
                            </div>
                            <div>
                                <label class="block text-xs font-bold text-slate-500 uppercase tracking-wider mb-1.5">Description (optional)</label>
                                <input v-model="itemForm.item_details" id="item-details" type="text" class="input-dark" placeholder="Served with fries">
                            </div>
                            <div class="flex items-center gap-3">
                                <input type="checkbox" v-model="itemForm.is_available" id="item-available" class="accent-saffron w-4 h-4">
                                <label for="item-available" class="text-sm font-semibold text-slate-300">Available on launch</label>
                            </div>
                        </div>
                        <div v-if="modalError" class="mt-4 p-3 rounded-lg bg-harissa/10 border border-harissa/30 text-harissa text-sm">{{ modalError }}</div>
                        <div class="flex gap-3 mt-6">
                            <button @click="showAddItem = false" class="btn btn-ghost flex-1">Cancel</button>
                            <button @click="saveItem" id="item-save-btn" class="btn btn-saffron flex-1">Add Item</button>
                        </div>
                    </div>
                </div>
            </template>
        </div>
    `,
    props: ['user'],
    setup(props) {
        const categories    = ref([]);
        const loading       = ref(true);
        const activeCategory = ref(null);

        // Inline price editor state
        const editingPriceId    = ref(null);
        const editingPriceValue = ref(0);

        // Stock toggle confirmation
        const stockConfirmItem = ref(null);

        // Modal state
        const showAddCategory = ref(false);
        const showAddItem     = ref(false);
        const addItemCatId    = ref(null);
        const modalError      = ref('');

        const catForm  = ref({ name_en: '', name_fr: '', name_ar: '' });
        const itemForm = ref({
            name_en: '', name_fr: '', name_ar: '',
            price: 0, item_details: '', is_available: true
        });

        // ── Filtered categories based on tab ───────────────────────────────
        const filteredCategories = computed(() => {
            if (activeCategory.value === null) return categories.value;
            return categories.value.filter(c => c.id === activeCategory.value);
        });

        // ── Load menu ───────────────────────────────────────────────────────
        const loadMenu = async () => {
            if (!props.user?.restaurant_id) { loading.value = false; return; }
            loading.value = true;
            try {
                const res = await api.get('/admin/menu/' + props.user.restaurant_id);
                categories.value = res.data;
            } catch (err) {
                console.error('[MenuManager] loadMenu error', err);
            } finally {
                loading.value = false;
            }
        };

        // ── Inline price edit ───────────────────────────────────────────────
        const startEditPrice = (item) => {
            editingPriceId.value    = item.id;
            editingPriceValue.value = item.price;
        };
        const savePrice = async (item) => {
            if (editingPriceValue.value <= 0) return;
            try {
                await api.patch(`/admin/menu/items/${item.id}`, { price: editingPriceValue.value });
                item.price = editingPriceValue.value;
            } catch (err) {
                console.error('[MenuManager] savePrice error', err);
            } finally {
                editingPriceId.value = null;
            }
        };

        // ── Stock toggle ────────────────────────────────────────────────────
        const promptStockToggle = (item) => { stockConfirmItem.value = item; };
        const confirmStockToggle = async () => {
            const item = stockConfirmItem.value;
            if (!item) return;
            stockConfirmItem.value = null;
            const newAvail = !item.is_available;
            try {
                await api.patch(`/admin/menu/items/${item.id}`, { is_available: newAvail });
                item.is_available = newAvail;
            } catch (err) {
                console.error('[MenuManager] stock toggle error', err);
            }
        };

        // ── Category CRUD ───────────────────────────────────────────────────
        const openAddCategoryModal = () => {
            catForm.value = { name_en: '', name_fr: '', name_ar: '' };
            modalError.value = '';
            showAddCategory.value = true;
        };
        const saveCategory = async () => {
            modalError.value = '';
            if (!catForm.value.name_en.trim()) { modalError.value = 'English name is required.'; return; }
            try {
                await api.post('/admin/menu/categories', {
                    ...catForm.value,
                    restaurant_id: props.user.restaurant_id
                });
                showAddCategory.value = false;
                await loadMenu();
            } catch (err) {
                modalError.value = err.response?.data?.detail || 'Failed to create category.';
            }
        };
        const deleteCategory = async (id) => {
            if (!confirm('Delete this category and all its items? This cannot be undone.')) return;
            try {
                await api.delete('/admin/menu/categories/' + id);
                await loadMenu();
            } catch (err) { console.error(err); }
        };

        // ── Item CRUD ────────────────────────────────────────────────────────
        const openAddItemModal = (catId) => {
            addItemCatId.value = catId;
            itemForm.value     = { name_en: '', name_fr: '', name_ar: '', price: 0, item_details: '', is_available: true };
            modalError.value   = '';
            showAddItem.value  = true;
        };
        const saveItem = async () => {
            modalError.value = '';
            if (!itemForm.value.name_en.trim()) { modalError.value = 'English name is required.'; return; }
            if (itemForm.value.price <= 0)       { modalError.value = 'Price must be greater than 0.'; return; }
            try {
                await api.post('/admin/menu/items', {
                    ...itemForm.value,
                    category_id: addItemCatId.value,
                    restaurant_id: props.user.restaurant_id,
                });
                showAddItem.value = false;
                await loadMenu();
            } catch (err) {
                modalError.value = err.response?.data?.detail || 'Failed to create item.';
            }
        };
        const deleteItem = async (id) => {
            if (!confirm('Delete this item?')) return;
            try {
                await api.delete('/admin/menu/items/' + id);
                await loadMenu();
            } catch (err) { console.error(err); }
        };

        onMounted(loadMenu);

        return {
            categories, loading, activeCategory, filteredCategories,
            editingPriceId, editingPriceValue, startEditPrice, savePrice,
            stockConfirmItem, promptStockToggle, confirmStockToggle,
            showAddCategory, catForm, openAddCategoryModal, saveCategory, deleteCategory,
            showAddItem, itemForm, openAddItemModal, saveItem, deleteItem,
            modalError,
        };
    }
};

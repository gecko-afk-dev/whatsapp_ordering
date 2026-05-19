import { ref, onMounted } from 'https://unpkg.com/vue@3/dist/vue.esm-browser.js';
import { api } from '../api.js';

export default {
    template: `
        <div>
            <div class="flex justify-between items-center mb-6">
                <h2 class="text-2xl font-bold text-slate-800">Menu Management</h2>
                <button @click="showAddCategory = true" class="btn-primary flex items-center text-sm">
                    <svg class="w-4 h-4 mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"></path></svg>
                    Add Category
                </button>
            </div>

            <div v-if="loading" class="text-center py-10 text-slate-500 animate-pulse">Loading menu...</div>

            <div v-else class="space-y-6">
                <div v-for="cat in categories" :key="cat.id" class="bg-white rounded-xl shadow-sm border border-slate-200 overflow-hidden">
                    <div class="bg-slate-50 px-6 py-4 border-b border-slate-200 flex justify-between items-center">
                        <h3 class="text-lg font-bold text-slate-800">{{ cat.name_en }} <span class="text-xs text-slate-400 ml-2 font-normal">{{ cat.name_fr }} / {{ cat.name_ar }}</span></h3>
                        <div class="space-x-2">
                            <button @click="openAddItem(cat.id)" class="text-sm text-blue-600 hover:text-blue-800 font-medium">Add Item</button>
                            <button @click="deleteCategory(cat.id)" class="text-sm text-red-600 hover:text-red-800 font-medium ml-4">Delete</button>
                        </div>
                    </div>
                    <div class="p-0">
                        <ul class="divide-y divide-slate-100">
                            <li v-for="item in cat.items" :key="item.id" class="px-6 py-4 hover:bg-slate-50 transition-colors">
                                <div class="flex justify-between items-start">
                                    <div>
                                        <h4 class="font-semibold text-slate-900">{{ item.name_en }}</h4>
                                        <p class="text-sm text-slate-500 mt-1">{{ item.price }} MAD</p>
                                    </div>
                                    <div class="flex items-center space-x-3">
                                        <span :class="item.is_available ? 'bg-emerald-100 text-emerald-800' : 'bg-red-100 text-red-800'" class="px-2 py-0.5 text-xs rounded-full font-medium">
                                            {{ item.is_available ? 'Available' : 'Sold Out' }}
                                        </span>
                                        <button @click="deleteItem(item.id)" class="text-slate-400 hover:text-red-600">
                                            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path></svg>
                                        </button>
                                    </div>
                                </div>
                            </li>
                            <li v-if="!cat.items || cat.items.length === 0" class="px-6 py-4 text-sm text-slate-500 italic">No items in this category.</li>
                        </ul>
                    </div>
                </div>
                <div v-if="categories.length === 0" class="text-center py-10 bg-white rounded-xl border border-slate-200">
                    <p class="text-slate-500">Your menu is empty.</p>
                </div>
            </div>
            
            <!-- Simple modals would go here for adding categories and items -->
        </div>
    `,
    props: ['user'],
    setup(props) {
        const categories = ref([]);
        const loading = ref(true);
        const showAddCategory = ref(false);

        const loadMenu = async () => {
            if (!props.user || !props.user.restaurant_id) {
                loading.value = false;
                return;
            }
            try {
                const res = await api.get('/admin/menu/' + props.user.restaurant_id);
                categories.value = res.data;
            } catch (err) {
                console.error(err);
            } finally {
                loading.value = false;
            }
        };

        const deleteCategory = async (id) => {
            if (!confirm('Delete this category and all its items?')) return;
            try {
                await api.delete('/admin/menu/categories/' + id);
                await loadMenu();
            } catch (err) { console.error(err); }
        };

        const deleteItem = async (id) => {
            if (!confirm('Delete this item?')) return;
            try {
                await api.delete('/admin/menu/items/' + id);
                await loadMenu();
            } catch (err) { console.error(err); }
        };

        const openAddItem = (catId) => {
            alert('Add item dialog placeholder');
        };

        onMounted(() => {
            loadMenu();
        });

        return { categories, loading, showAddCategory, deleteCategory, deleteItem, openAddItem };
    }
}

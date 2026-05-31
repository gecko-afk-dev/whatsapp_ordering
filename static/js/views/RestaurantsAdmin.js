import { ref, onMounted } from 'https://unpkg.com/vue@3/dist/vue.esm-browser.js';
import { api } from '../api.js';

export default {
    template: `
        <div>
            <div class="flex justify-between items-center mb-6">
                <h2 class="text-2xl font-bold text-slate-800">Restaurant Management</h2>
                <button @click="openModal" class="bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded-lg font-medium flex items-center shadow-sm">
                    <svg class="w-5 h-5 mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"></path></svg>
                    Add Restaurant
                </button>
            </div>

            <!-- List -->
            <div class="bg-white shadow-sm border border-slate-200 rounded-xl overflow-hidden">
                <table class="min-w-full divide-y divide-slate-200">
                    <thead class="bg-slate-50">
                        <tr>
                            <th class="px-6 py-4 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider">Restaurant</th>
                            <th class="px-6 py-4 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider">Contact Email</th>
                            <th class="px-6 py-4 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider">Commission</th>
                            <th class="px-6 py-4 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider">Status</th>
                            <th class="px-6 py-4 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider">Actions</th>
                        </tr>
                    </thead>
                    <tbody class="divide-y divide-slate-200">
                        <tr v-for="r in restaurants" :key="r.id" class="hover:bg-slate-50 transition-colors">
                            <td class="px-6 py-4 whitespace-nowrap font-medium text-slate-900">{{ r.name }}</td>
                            <td class="px-6 py-4 whitespace-nowrap text-slate-600">{{ r.contact_email }}</td>
                            <td class="px-6 py-4 whitespace-nowrap text-slate-600">{{ r.commission_rate * 100 }}%</td>
                            <td class="px-6 py-4 whitespace-nowrap">
                                <span :class="r.status === 'active' ? 'bg-emerald-100 text-emerald-800' : 'bg-red-100 text-red-800'" class="px-2.5 py-1 text-xs font-semibold rounded-full">
                                    {{ r.status }}
                                </span>
                            </td>
                            <td class="px-6 py-4 whitespace-nowrap text-sm font-medium">
                                <button v-if="r.status === 'active'" @click="suspend(r.id)" class="text-red-600 hover:text-red-900 mr-3">Suspend</button>
                                <button v-else @click="activate(r.id)" class="text-emerald-600 hover:text-emerald-900">Activate</button>
                            </td>
                        </tr>
                        <tr v-if="restaurants.length === 0 && !loading">
                            <td colspan="5" class="px-6 py-8 text-center text-slate-500">No restaurants found.</td>
                        </tr>
                    </tbody>
                </table>
            </div>

            <!-- Loading -->
            <div v-if="loading" class="mt-6 text-center text-slate-500">Loading...</div>

            <!-- Modal Form -->
            <div v-if="showCreate" class="fixed inset-0 bg-slate-900 bg-opacity-50 flex items-center justify-center p-4 z-50">
                <div class="bg-white rounded-2xl shadow-xl max-w-lg w-full max-h-[90vh] overflow-y-auto p-6 border border-slate-100">
                    <h3 class="text-xl font-bold text-slate-900 mb-4">Add New Restaurant</h3>
                    
                    <div class="space-y-4">
                        <div>
                            <label class="block text-sm font-semibold text-slate-700 mb-1">Restaurant Name</label>
                            <input v-model="form.name" type="text" class="w-full border border-slate-300 rounded-lg p-2.5" placeholder="Pizzeria Napoli" />
                        </div>
                        <div>
                            <label class="block text-sm font-semibold text-slate-700 mb-1">Contact Email</label>
                            <input v-model="form.contact_email" type="email" class="w-full border border-slate-300 rounded-lg p-2.5" placeholder="owner@pizzeria.com" />
                        </div>
                        <div>
                            <label class="block text-sm font-semibold text-slate-700 mb-1">WhatsApp Phone Number</label>
                            <input v-model="form.wa_phone_number" type="text" class="w-full border border-slate-300 rounded-lg p-2.5" placeholder="+212600000000" />
                        </div>
                        <div>
                            <label class="block text-sm font-semibold text-slate-700 mb-1">Meta Phone Number ID</label>
                            <input v-model="form.phone_number_id" type="text" class="w-full border border-slate-300 rounded-lg p-2.5" />
                        </div>
                        <div>
                            <label class="block text-sm font-semibold text-slate-700 mb-1">Permanent API Token</label>
                            <textarea v-model="form.api_token" class="w-full border border-slate-300 rounded-lg p-2.5 h-16"></textarea>
                        </div>
                        <div>
                            <label class="block text-sm font-semibold text-slate-700 mb-1">Owner WhatsApp ID (Manager recipient)</label>
                            <input v-model="form.owner_wa_id" type="text" class="w-full border border-slate-300 rounded-lg p-2.5" placeholder="212611223344" />
                        </div>
                        <div class="grid grid-cols-2 gap-4">
                            <div>
                                <label class="block text-sm font-semibold text-slate-700 mb-1">Commission Rate (0.0 to 1.0)</label>
                                <input v-model.number="form.commission_rate" type="number" step="0.01" class="w-full border border-slate-300 rounded-lg p-2.5" />
                            </div>
                            <div>
                                <label class="block text-sm font-semibold text-slate-700 mb-1">Cuisine Type</label>
                                <input v-model="form.cuisine_type" type="text" class="w-full border border-slate-300 rounded-lg p-2.5" placeholder="Italian" />
                            </div>
                        </div>
                    </div>

                    <div v-if="error" class="mt-4 p-3 bg-red-50 text-red-700 rounded-lg text-sm">{{ error }}</div>

                    <div class="flex justify-end space-x-3 mt-6 border-t pt-4">
                        <button @click="showCreate = false" class="px-4 py-2 border rounded-lg hover:bg-slate-50 text-slate-700 font-medium">Cancel</button>
                        <button @click="save" class="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 font-medium">Create</button>
                    </div>
                </div>
            </div>
        </div>
    `,
    setup() {
        const restaurants = ref([]);
        const loading = ref(true);
        const showCreate = ref(false);
        const error = ref('');

        const form = ref({
            name: '',
            wa_phone_number: '',
            api_token: '',
            phone_number_id: '',
            owner_wa_id: '',
            cuisine_type: '',
            contact_email: '',
            commission_rate: 0.20
        });

        const openModal = () => {
            error.value = '';
            showCreate.value = true;
        };

        const loadRestaurants = async () => {
            loading.value = true;
            try {
                const res = await api.get('/admin/restaurants');
                restaurants.value = res.data;
            } catch (err) {
                console.error(err);
            } finally {
                loading.value = false;
            }
        };

        const save = async () => {
            error.value = '';
            try {
                await api.post('/admin/restaurants', form.value);
                showCreate.value = false;
                await loadRestaurants();
                form.value = {
                    name: '',
                    wa_phone_number: '',
                    api_token: '',
                    phone_number_id: '',
                    owner_wa_id: '',
                    cuisine_type: '',
                    contact_email: '',
                    commission_rate: 0.20
                };
            } catch (err) {
                error.value = err.response?.data?.detail || 'Failed to create restaurant.';
            }
        };

        const suspend = async (id) => {
            try {
                await api.post(`/admin/restaurants/${id}/suspend`);
                await loadRestaurants();
            } catch (err) { console.error(err); }
        };

        const activate = async (id) => {
            try {
                await api.post(`/admin/restaurants/${id}/activate`);
                await loadRestaurants();
            } catch (err) { console.error(err); }
        };

        onMounted(() => {
            loadRestaurants();
        });

        return { restaurants, loading, showCreate, error, form, openModal, save, suspend, activate };
    }
}

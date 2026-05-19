import { ref, onMounted } from 'https://unpkg.com/vue@3/dist/vue.esm-browser.js';
import { api } from '../api.js';

export default {
    template: `
        <div>
            <div class="flex justify-between items-center mb-6">
                <h2 class="text-2xl font-bold text-slate-800">Restaurant Management</h2>
                <button @click="showCreate = true" class="btn-primary flex items-center">
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
                            <th class="px-6 py-4 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider">Status</th>
                            <th class="px-6 py-4 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider">Actions</th>
                        </tr>
                    </thead>
                    <tbody class="divide-y divide-slate-200">
                        <tr v-for="r in restaurants" :key="r.id" class="hover:bg-slate-50 transition-colors">
                            <td class="px-6 py-4 whitespace-nowrap font-medium text-slate-900">{{ r.name }}</td>
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
                            <td colspan="3" class="px-6 py-8 text-center text-slate-500">No restaurants found.</td>
                        </tr>
                    </tbody>
                </table>
            </div>
            
            <!-- Loading -->
            <div v-if="loading" class="mt-6 text-center text-slate-500">Loading...</div>

            <!-- Modal logic omitted for brevity in Phase 0 scaffolding (would add full form here) -->
        </div>
    `,
    setup() {
        const restaurants = ref([]);
        const loading = ref(true);
        const showCreate = ref(false);

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

        return { restaurants, loading, showCreate, suspend, activate };
    }
}

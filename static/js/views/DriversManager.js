import { ref, onMounted } from 'https://unpkg.com/vue@3/dist/vue.esm-browser.js';
import { api } from '../api.js';

export default {
    template: `
        <div>
            <div class="flex justify-between items-center mb-6">
                <h2 class="text-2xl font-bold text-slate-800">Driver Management</h2>
            </div>
            
            <div class="grid grid-cols-1 md:grid-cols-3 gap-6">
                <!-- Add Driver Form -->
                <div class="bg-white p-6 rounded-xl shadow-sm border border-slate-200 h-fit">
                    <h3 class="text-lg font-bold text-slate-800 mb-4">Add New Driver</h3>
                    <form @submit.prevent="addDriver" class="space-y-4">
                        <div>
                            <label class="block text-sm font-medium text-slate-700 mb-1">Name</label>
                            <input v-model="newDriver.name" type="text" required class="input-premium" placeholder="e.g. John Doe">
                        </div>
                        <div>
                            <label class="block text-sm font-medium text-slate-700 mb-1">WhatsApp Number</label>
                            <input v-model="newDriver.wa_id" type="text" required class="input-premium" placeholder="e.g. 212600000000">
                        </div>
                        <button type="submit" :disabled="adding" class="w-full btn-primary mt-2">
                            {{ adding ? 'Adding...' : 'Add Driver' }}
                        </button>
                    </form>
                </div>
                
                <!-- Drivers List -->
                <div class="md:col-span-2">
                    <div class="bg-white rounded-xl shadow-sm border border-slate-200 overflow-hidden">
                        <table class="min-w-full divide-y divide-slate-200">
                            <thead class="bg-slate-50">
                                <tr>
                                    <th class="px-6 py-4 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider">Driver Name</th>
                                    <th class="px-6 py-4 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider">WhatsApp ID</th>
                                    <th class="px-6 py-4 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider">Status</th>
                                    <th class="px-6 py-4 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider">Actions</th>
                                </tr>
                            </thead>
                            <tbody class="divide-y divide-slate-200">
                                <tr v-for="d in drivers" :key="d.id" class="hover:bg-slate-50 transition-colors">
                                    <td class="px-6 py-4 whitespace-nowrap font-medium text-slate-900">{{ d.name }}</td>
                                    <td class="px-6 py-4 whitespace-nowrap text-sm text-slate-500">{{ d.wa_id }}</td>
                                    <td class="px-6 py-4 whitespace-nowrap">
                                        <span :class="d.is_active ? 'bg-emerald-100 text-emerald-800' : 'bg-slate-100 text-slate-800'" class="px-2.5 py-1 text-xs font-semibold rounded-full">
                                            {{ d.is_active ? 'Active' : 'Inactive' }}
                                        </span>
                                    </td>
                                    <td class="px-6 py-4 whitespace-nowrap text-sm font-medium">
                                        <button @click="deleteDriver(d.id)" class="text-red-600 hover:text-red-900">Remove</button>
                                    </td>
                                </tr>
                                <tr v-if="drivers.length === 0 && !loading">
                                    <td colspan="4" class="px-6 py-8 text-center text-slate-500">No drivers added yet.</td>
                                </tr>
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>
        </div>
    `,
    setup() {
        const drivers = ref([]);
        const loading = ref(true);
        const adding = ref(false);
        const newDriver = ref({ name: '', wa_id: '' });

        const loadDrivers = async () => {
            loading.value = true;
            try {
                const res = await api.get('/admin/drivers');
                drivers.value = res.data;
            } catch (err) {
                console.error(err);
            } finally {
                loading.value = false;
            }
        };

        const addDriver = async () => {
            adding.value = true;
            try {
                await api.post('/admin/drivers', newDriver.value);
                newDriver.value = { name: '', wa_id: '' };
                await loadDrivers();
            } catch (err) {
                console.error(err);
                alert("Failed to add driver. Check if WhatsApp number is valid/unique.");
            } finally {
                adding.value = false;
            }
        };

        const deleteDriver = async (id) => {
            if (!confirm("Are you sure you want to remove this driver?")) return;
            try {
                await api.delete('/admin/drivers/' + id);
                await loadDrivers();
            } catch (err) {
                console.error(err);
            }
        };

        onMounted(() => {
            loadDrivers();
        });

        return { drivers, loading, adding, newDriver, addDriver, deleteDriver };
    }
}

import { ref, onMounted } from 'https://unpkg.com/vue@3/dist/vue.esm-browser.js';
import { api } from '../api.js';

export default {
    name: 'StaffManager',
    template: `
        <div class="space-y-6">
            <!-- Header section -->
            <div class="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4 bg-white p-6 rounded-2xl border border-slate-100 shadow-sm">
                <div>
                    <h2 class="text-2xl font-bold text-slate-800 tracking-tight">Staff Management</h2>
                    <p class="text-sm text-slate-500 mt-1">Manage Cashiers and Kitchen Staff. Invite new members to collaborate.</p>
                </div>
                <button @click="showInviteModal = true" class="inline-flex items-center px-4 py-2.5 bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium rounded-xl shadow-sm hover:shadow transition-all duration-200 gap-2">
                    <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" viewBox="0 0 20 20" fill="currentColor">
                        <path fill-rule="evenodd" d="M10 3a1 1 0 011 1v5h5a1 1 0 110 2h-5v5a1 1 0 11-2 0v-5H4a1 1 0 110-2h5V4a1 1 0 011-1z" clip-rule="evenodd" />
                    </svg>
                    Invite Staff Member
                </button>
            </div>

            <!-- Error/Success Alerts -->
            <div v-if="alert.show" :class="alert.type === 'success' ? 'bg-emerald-50 border-emerald-200 text-emerald-800' : 'bg-rose-50 border-rose-200 text-rose-800'" class="flex items-center p-4 rounded-xl border text-sm animate-fadeIn">
                <span class="font-medium mr-2">{{ alert.type === 'success' ? 'Success:' : 'Error:' }}</span>
                <span>{{ alert.message }}</span>
                <button @click="alert.show = false" class="ml-auto text-slate-400 hover:text-slate-600">
                    <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
                    </svg>
                </button>
            </div>

            <!-- Staff List Card -->
            <div class="bg-white rounded-2xl border border-slate-100 shadow-sm overflow-hidden">
                <div v-if="loading" class="flex flex-col items-center justify-center py-12">
                    <div class="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
                    <span class="text-sm text-slate-500 mt-3 font-medium">Loading staff list...</span>
                </div>
                
                <div v-else-if="staffList.length === 0" class="flex flex-col items-center justify-center py-16 text-center px-4">
                    <div class="w-16 h-16 bg-slate-50 rounded-2xl flex items-center justify-center text-slate-400 mb-4">
                        <svg xmlns="http://www.w3.org/2000/svg" class="h-8 w-8" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4.354a4 4 0 110 5.292M15 21H3v-1a6 6 0 0112 0v1zm0 0h6v-1a6 6 0 00-9-5.197M13 7a4 4 0 11-8 0 4 4 0 018 0z" />
                        </svg>
                    </div>
                    <h3 class="text-lg font-bold text-slate-700">No staff members found</h3>
                    <p class="text-sm text-slate-400 mt-1 max-w-sm">You haven't added any staff members yet. Invite cashiers or kitchen staff to manage orders.</p>
                </div>

                <div v-else class="overflow-x-auto">
                    <table class="min-w-full divide-y divide-slate-100">
                        <thead class="bg-slate-50/50">
                            <tr>
                                <th class="px-6 py-3.5 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider">Email</th>
                                <th class="px-6 py-3.5 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider">Role</th>
                                <th class="px-6 py-3.5 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider">Status</th>
                                <th class="px-6 py-3.5 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider">Setup Status</th>
                                <th class="px-6 py-3.5 text-right text-xs font-semibold text-slate-500 uppercase tracking-wider">Actions</th>
                            </tr>
                        </thead>
                        <tbody class="divide-y divide-slate-100">
                            <tr v-for="member in staffList" :key="member.id" class="hover:bg-slate-50/40 transition-colors">
                                <td class="px-6 py-4 whitespace-nowrap">
                                    <div class="text-sm font-medium text-slate-800">{{ member.email }}</div>
                                </td>
                                <td class="px-6 py-4 whitespace-nowrap">
                                    <span :class="roleBadgeClass(member.role)" class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold tracking-wide">
                                        {{ formatRole(member.role) }}
                                    </span>
                                </td>
                                <td class="px-6 py-4 whitespace-nowrap">
                                    <button @click="toggleStatus(member)" 
                                            :disabled="togglingId === member.id"
                                            :class="member.is_active ? 'bg-emerald-500 text-white' : 'bg-slate-200 text-slate-600'" 
                                            class="relative inline-flex h-6 w-11 flex-shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2">
                                        <span :class="member.is_active ? 'translate-x-5' : 'translate-x-0'" class="pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out"></span>
                                    </button>
                                </td>
                                <td class="px-6 py-4 whitespace-nowrap">
                                    <span :class="member.requires_password_change ? 'bg-amber-50 text-amber-700 border border-amber-200' : 'bg-slate-100 text-slate-600 border border-slate-200'" class="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium">
                                        {{ member.requires_password_change ? 'Pending Setup' : 'Active Account' }}
                                    </span>
                                </td>
                                <td class="px-6 py-4 whitespace-nowrap text-right text-sm font-medium">
                                    <button @click="confirmDelete(member)" class="text-rose-600 hover:text-rose-800 px-3 py-1.5 rounded-lg hover:bg-rose-50 transition-all duration-200">
                                        Remove
                                    </button>
                                </td>
                            </tr>
                        </tbody>
                    </table>
                </div>
            </div>

            <!-- Invite Modal -->
            <div v-if="showInviteModal" class="fixed inset-0 z-50 overflow-y-auto flex items-center justify-center p-4 bg-slate-900/40 backdrop-blur-sm animate-fadeIn">
                <div class="bg-white rounded-2xl shadow-xl border border-slate-100 w-full max-w-md overflow-hidden transform transition-all duration-300 scale-100">
                    <div class="px-6 py-4 bg-slate-50 border-b border-slate-100 flex justify-between items-center">
                        <h3 class="text-lg font-bold text-slate-800">Invite Staff Member</h3>
                        <button @click="closeInviteModal" class="text-slate-400 hover:text-slate-600">
                            <svg xmlns="http://www.w3.org/2000/svg" class="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
                            </svg>
                        </button>
                    </div>

                    <form @submit.prevent="inviteStaff" class="p-6 space-y-4">
                        <div>
                            <label class="block text-xs font-bold text-slate-500 uppercase tracking-wide mb-1.5">Email Address</label>
                            <input v-model="inviteForm.email" type="email" required placeholder="staff@geqo.com" class="w-full px-4 py-2.5 rounded-xl border border-slate-200 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition-colors" />
                        </div>

                        <div>
                            <label class="block text-xs font-bold text-slate-500 uppercase tracking-wide mb-1.5">Role Assignment</label>
                            <select v-model="inviteForm.role" required class="w-full px-4 py-2.5 rounded-xl border border-slate-200 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition-colors bg-white">
                                <option value="cashier">Cashier (Full order management & dispatch)</option>
                                <option value="kitchen_staff">Kitchen Staff (Read-only monitor view)</option>
                            </select>
                        </div>

                        <div class="flex gap-3 justify-end pt-4 border-t border-slate-100 mt-6">
                            <button type="button" @click="closeInviteModal" class="px-4 py-2.5 border border-slate-200 text-slate-600 text-sm font-medium rounded-xl hover:bg-slate-50 transition-colors">
                                Cancel
                            </button>
                            <button type="submit" :disabled="submitting" class="px-4 py-2.5 bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium rounded-xl shadow-sm transition-colors flex items-center gap-2">
                                <span v-if="submitting" class="animate-spin rounded-full h-4 w-4 border-b-2 border-white"></span>
                                {{ submitting ? 'Sending invite...' : 'Send Invite' }}
                            </button>
                        </div>
                    </form>
                </div>
            </div>

            <!-- Delete Confirmation Modal -->
            <div v-if="showDeleteModal" class="fixed inset-0 z-50 overflow-y-auto flex items-center justify-center p-4 bg-slate-900/40 backdrop-blur-sm animate-fadeIn">
                <div class="bg-white rounded-2xl shadow-xl border border-slate-100 w-full max-w-sm overflow-hidden p-6 text-center">
                    <div class="w-12 h-12 bg-rose-50 rounded-full flex items-center justify-center text-rose-600 mx-auto mb-4">
                        <svg xmlns="http://www.w3.org/2000/svg" class="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                        </svg>
                    </div>
                    <h3 class="text-lg font-bold text-slate-800">Remove Staff Member</h3>
                    <p class="text-sm text-slate-500 mt-2">Are you sure you want to remove <span class="font-semibold text-slate-700">{{ memberToDelete?.email }}</span>? This will permanently disable their access.</p>
                    
                    <div class="flex gap-3 justify-center mt-6">
                        <button @click="showDeleteModal = false" class="px-4 py-2 border border-slate-200 text-slate-600 text-sm font-medium rounded-xl hover:bg-slate-50 transition-colors">
                            Cancel
                        </button>
                        <button @click="deleteStaff" :disabled="deleting" class="px-4 py-2 bg-rose-600 hover:bg-rose-700 text-white text-sm font-medium rounded-xl shadow-sm transition-colors flex items-center gap-2">
                            <span v-if="deleting" class="animate-spin rounded-full h-4 w-4 border-b-2 border-white"></span>
                            {{ deleting ? 'Removing...' : 'Confirm Remove' }}
                        </button>
                    </div>
                </div>
            </div>
        </div>
    `,
    setup() {
        const staffList = ref([]);
        const loading = ref(true);
        const submitting = ref(false);
        const deleting = ref(false);
        const togglingId = ref(null);
        const showInviteModal = ref(false);
        const showDeleteModal = ref(false);
        const memberToDelete = ref(null);

        const inviteForm = ref({
            email: '',
            role: 'cashier'
        });

        const alert = ref({
            show: false,
            type: 'success',
            message: ''
        });

        const fetchStaff = async () => {
            loading.value = true;
            try {
                const res = await api.get('/admin/staff');
                staffList.value = res.data;
            } catch (err) {
                console.error(err);
                showAlert('danger', 'Failed to retrieve staff members. Please verify permissions.');
            } finally {
                loading.value = false;
            }
        };

        const inviteStaff = async () => {
            submitting.value = true;
            try {
                const res = await api.post('/admin/staff/invite', inviteForm.value);
                showAlert('success', res.data.message || 'Staff invited successfully.');
                closeInviteModal();
                await fetchStaff();
            } catch (err) {
                console.error(err);
                const msg = err.response?.data?.detail || 'An error occurred during staff invitation.';
                showAlert('danger', msg);
            } finally {
                submitting.value = false;
            }
        };

        const toggleStatus = async (member) => {
            togglingId.value = member.id;
            try {
                const res = await api.post(`/admin/staff/${member.id}/toggle`, {});
                member.is_active = res.data.is_active;
                showAlert('success', res.data.message);
            } catch (err) {
                console.error(err);
                showAlert('danger', 'Failed to toggle status.');
            } finally {
                togglingId.value = null;
            }
        };

        const confirmDelete = (member) => {
            memberToDelete.value = member;
            showDeleteModal.value = true;
        };

        const deleteStaff = async () => {
            if (!memberToDelete.value) return;
            deleting.value = true;
            try {
                const res = await api.delete(`/admin/staff/${memberToDelete.value.id}`);
                showAlert('success', res.data.message || 'Staff member removed.');
                showDeleteModal.value = false;
                memberToDelete.value = null;
                await fetchStaff();
            } catch (err) {
                console.error(err);
                showAlert('danger', 'Failed to remove staff member.');
            } finally {
                deleting.value = false;
            }
        };

        const showAlert = (type, message) => {
            alert.value = { show: true, type, message };
            setTimeout(() => {
                alert.value.show = false;
            }, 6000);
        };

        const closeInviteModal = () => {
            showInviteModal.value = false;
            inviteForm.value = { email: '', role: 'cashier' };
        };

        const formatRole = (role) => {
            if (role === 'cashier') return 'Cashier';
            if (role === 'kitchen_staff') return 'Kitchen Staff';
            return role;
        };

        const roleBadgeClass = (role) => {
            if (role === 'cashier') return 'bg-indigo-50 text-indigo-700 border border-indigo-200';
            if (role === 'kitchen_staff') return 'bg-teal-50 text-teal-700 border border-teal-200';
            return 'bg-slate-50 text-slate-700 border border-slate-200';
        };

        onMounted(() => {
            fetchStaff();
        });

        return {
            staffList,
            loading,
            submitting,
            deleting,
            togglingId,
            showInviteModal,
            showDeleteModal,
            memberToDelete,
            inviteForm,
            alert,
            closeInviteModal,
            inviteStaff,
            toggleStatus,
            confirmDelete,
            deleteStaff,
            formatRole,
            roleBadgeClass
        };
    }
};

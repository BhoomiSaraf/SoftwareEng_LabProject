/**
 * Smart Attendance System - Reports & CSV Export Controller
 */

(function () {
    const courseFilter = document.getElementById('reportCourseFilter');
    const statusFilter = document.getElementById('reportStatusFilter');
    const searchInput = document.getElementById('reportSearchInput');
    const exportBtn = document.getElementById('exportCsvBtn');
    const reportRows = document.querySelectorAll('.report-row');

    // Summary Card Displays
    const summaryStudents = document.getElementById('summaryTotalStudents');
    const summaryEligible = document.getElementById('summaryEligibleCount');
    const summaryWarning = document.getElementById('summaryWarningCount');

    // Filter Logic
    function applyFilters() {
        const selectedCourse = courseFilter?.value || 'all';
        const selectedStatus = statusFilter?.value || 'all';
        const q = (searchInput?.value || '').toLowerCase().trim();

        let visibleCount = 0;
        let eligibleCount = 0;
        let warningCount = 0;

        reportRows.forEach(row => {
            const course = row.dataset.course;
            const status = row.dataset.status;
            const name = row.dataset.name || '';
            const roll = row.dataset.roll || '';

            const matchesCourse = selectedCourse === 'all' || course === selectedCourse;
            const matchesStatus = selectedStatus === 'all' || status === selectedStatus;
            const matchesQuery = !q || name.includes(q) || roll.includes(q);

            if (matchesCourse && matchesStatus && matchesQuery) {
                row.style.display = '';
                visibleCount++;
                if (status === 'eligible') eligibleCount++;
                else warningCount++;
            } else {
                row.style.display = 'none';
            }
        });

        // Update summary metrics dynamically
        if (summaryStudents) summaryStudents.textContent = visibleCount;
        if (summaryEligible) summaryEligible.textContent = eligibleCount;
        if (summaryWarning) summaryWarning.textContent = warningCount;
    }

    courseFilter?.addEventListener('change', applyFilters);
    statusFilter?.addEventListener('change', applyFilters);
    searchInput?.addEventListener('input', applyFilters);

    // CSV Export Handler
    exportBtn?.addEventListener('click', async () => {
        const selectedCourse = courseFilter?.value || 'all';
        exportBtn.disabled = true;
        exportBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span> Generating CSV...';

        try {
            // Attempt backend export endpoint
            const url = `/api/reports/export-csv?course_id=${encodeURIComponent(selectedCourse)}`;
            const response = await fetch(url);

            if (response.ok && response.headers.get('content-type')?.includes('text/csv')) {
                const blob = await response.blob();
                downloadBlob(blob, `smart_attendance_report_${selectedCourse}.csv`);
                showToast('Attendance report exported successfully (Server)', 'success');
            } else {
                // Client-side fallback from visible table data
                exportTableToCsv();
                showToast('Attendance report exported successfully (Client)', 'success');
            }
        } catch (err) {
            console.warn('Backend CSV export unavailable, utilizing client generator fallback:', err);
            exportTableToCsv();
            showToast('Attendance report exported successfully', 'success');
        } finally {
            exportBtn.disabled = false;
            exportBtn.innerHTML = '<i class="bi bi-file-earmark-arrow-down-fill me-1"></i> Export CSV Report';
        }
    });

    // Client-side CSV generator fallback
    function exportTableToCsv() {
        const rows = [];
        rows.push(['Roll Number', 'Student Name', 'Course', 'Attended Sessions', 'Total Sessions', 'Attendance Percentage', 'Status']);

        reportRows.forEach(row => {
            if (row.style.display !== 'none') {
                const cells = row.querySelectorAll('td');
                if (cells.length >= 6) {
                    const rollNo = cells[0].textContent.trim();
                    const name = cells[1].textContent.trim();
                    const course = cells[2].textContent.trim();
                    const attendedText = cells[3].textContent.trim().replace(/\s+/g, ' ');
                    const [attended, total] = attendedText.split('/').map(s => s.trim());
                    const pctText = cells[4].querySelector('.font-monospace')?.textContent.trim() || '';
                    const statusText = cells[5].textContent.trim();

                    rows.push([
                        `"${rollNo}"`,
                        `"${name}"`,
                        `"${course}"`,
                        attended || '0',
                        total || '0',
                        `"${pctText}"`,
                        `"${statusText}"`
                    ]);
                }
            }
        });

        const csvContent = rows.map(e => e.join(',')).join('\n');
        const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
        downloadBlob(blob, `smart_attendance_report_${new Date().toISOString().slice(0,10)}.csv`);
    }

    function downloadBlob(blob, filename) {
        const link = document.createElement('a');
        const url = URL.createObjectURL(blob);
        link.setAttribute('href', url);
        link.setAttribute('download', filename);
        link.style.visibility = 'hidden';
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
    }
})();

import pdfMake from 'pdfmake/build/pdfmake';
import pdfFonts from 'pdfmake/build/vfs_fonts';

pdfMake.vfs = pdfFonts.pdfMake.vfs;

interface StepInfo {
    id: string;
    name: string;
    category?: string;
    description?: string;
    params?: Record<string, any>;
    duration_min?: number;
}

interface RoleInfo {
    id: string;
    name: string;
    color?: string;
}

/**
 * Generate a PDF for a single role's SOP (Standard Operating Procedure).
 * One PDF per role showing steps in that role's swimlane.
 */
export function generateSopPdf(
    experimentName: string,
    protocolName: string,
    roleName: string,
    steps: StepInfo[]
) {
    const now = new Date();
    const dateStr = now.toLocaleDateString('en-US', {
        year: 'numeric',
        month: 'short',
        day: 'numeric',
    });

    const docDefinition: any = {
        pageSize: 'LETTER',
        margins: [50, 50, 50, 70],
        header: {
            text: 'STANDARD OPERATING PROCEDURE',
            fontSize: 10,
            alignment: 'center',
            color: '#666',
            margin: [0, 10, 0, 0],
        },
        footer: (currentPage: number, pageCount: number) => ({
            text: `Page ${currentPage} of ${pageCount}`,
            fontSize: 8,
            alignment: 'center',
            color: '#999',
            margin: [0, 10, 0, 0],
        }),
        content: [
            // Title Section
            {
                text: 'Standard Operating Procedure',
                fontSize: 24,
                bold: true,
                alignment: 'center',
                margin: [0, 0, 0, 20],
            },

            // Document Info
            {
                columns: [
                    {
                        text: [
                            { text: 'Experiment: ', bold: true },
                            experimentName,
                        ],
                        fontSize: 11,
                        margin: [0, 0, 0, 8],
                    },
                    {
                        text: [{ text: 'Date: ', bold: true }, dateStr],
                        fontSize: 11,
                        alignment: 'right',
                    },
                ],
                margin: [0, 0, 0, 20],
            },

            {
                columns: [
                    {
                        text: [
                            { text: 'Protocol: ', bold: true },
                            protocolName,
                        ],
                        fontSize: 11,
                        margin: [0, 0, 0, 8],
                    },
                    {
                        text: [{ text: 'Role: ', bold: true }, roleName],
                        fontSize: 11,
                        alignment: 'right',
                    },
                ],
                margin: [0, 0, 0, 30],
            },

            // Steps Table
            {
                text: 'Steps',
                fontSize: 14,
                bold: true,
                margin: [0, 0, 0, 12],
            },

            {
                table: {
                    headerRows: 1,
                    widths: ['8%', '22%', '25%', '25%', '20%'],
                    body: [
                        // Header
                        [
                            {
                                text: 'Step',
                                bold: true,
                                fillColor: '#f3f4f6',
                                fontSize: 10,
                            },
                            {
                                text: 'Name',
                                bold: true,
                                fillColor: '#f3f4f6',
                                fontSize: 10,
                            },
                            {
                                text: 'Description',
                                bold: true,
                                fillColor: '#f3f4f6',
                                fontSize: 10,
                            },
                            {
                                text: 'Parameters',
                                bold: true,
                                fillColor: '#f3f4f6',
                                fontSize: 10,
                            },
                            {
                                text: 'Duration',
                                bold: true,
                                fillColor: '#f3f4f6',
                                fontSize: 10,
                            },
                        ],
                        // Data rows
                        ...steps.map((step, idx) => [
                            {
                                text: (idx + 1).toString(),
                                fontSize: 9,
                            },
                            {
                                text: step.name,
                                fontSize: 9,
                            },
                            {
                                text: step.description || '--',
                                fontSize: 8,
                            },
                            {
                                text: formatParams(step.params),
                                fontSize: 8,
                            },
                            {
                                text: step.duration_min
                                    ? `${step.duration_min}m`
                                    : '--',
                                fontSize: 9,
                            },
                        ]),
                    ],
                },
                margin: [0, 0, 0, 40],
            },

            // Signature Block
            {
                text: 'Approvals',
                fontSize: 12,
                bold: true,
                margin: [0, 0, 0, 20],
            },

            {
                columns: [
                    {
                        stack: [
                            {
                                text: '_______________________',
                                fontSize: 9,
                                margin: [0, 30, 0, 0],
                            },
                            {
                                text: 'Prepared by (Name/Date)',
                                fontSize: 8,
                                color: '#666',
                            },
                        ],
                        width: '48%',
                    },
                    {
                        width: '4%',
                    },
                    {
                        stack: [
                            {
                                text: '_______________________',
                                fontSize: 9,
                                margin: [0, 30, 0, 0],
                            },
                            {
                                text: 'Reviewed by (Name/Date)',
                                fontSize: 8,
                                color: '#666',
                            },
                        ],
                        width: '48%',
                    },
                ],
            },
        ],
    };

    pdfMake.createPdf(docDefinition).download(
        `SOP_${experimentName}_${roleName}.pdf`
    );
}

/**
 * Generate a batch record PDF showing all steps across all roles.
 * This is a data entry template that can be filled in by hand or digitally.
 */
export function generateBatchRecordPdf(
    experimentName: string,
    protocolName: string,
    roles: RoleInfo[],
    steps: Array<StepInfo & { roleId: string; roleName: string }>,
    filled: boolean = false,
    executionData?: Record<string, any>
) {
    const now = new Date();
    const dateStr = now.toLocaleDateString('en-US', {
        year: 'numeric',
        month: 'short',
        day: 'numeric',
    });

    const docDefinition: any = {
        pageSize: 'LETTER',
        margins: [40, 40, 40, 60],
        header: {
            text: 'BATCH RECORD',
            fontSize: 10,
            alignment: 'center',
            color: '#666',
            margin: [0, 10, 0, 0],
        },
        footer: (currentPage: number, pageCount: number) => ({
            text: `Page ${currentPage} of ${pageCount}`,
            fontSize: 8,
            alignment: 'center',
            color: '#999',
            margin: [0, 10, 0, 0],
        }),
        content: [
            // Title
            {
                text: 'Batch Record',
                fontSize: 20,
                bold: true,
                alignment: 'center',
                margin: [0, 0, 0, 20],
            },

            // Header Info
            {
                columns: [
                    {
                        text: [
                            { text: 'Experiment: ', bold: true },
                            experimentName,
                        ],
                        fontSize: 10,
                    },
                    {
                        text: [{ text: 'Date: ', bold: true }, dateStr],
                        fontSize: 10,
                        alignment: 'right',
                    },
                ],
                margin: [0, 0, 0, 8],
            },

            {
                columns: [
                    {
                        text: [
                            { text: 'Protocol: ', bold: true },
                            protocolName,
                        ],
                        fontSize: 10,
                    },
                    {
                        text: [
                            { text: 'Lot/Batch #: ', bold: true },
                            '_______________',
                        ],
                        fontSize: 10,
                        alignment: 'right',
                    },
                ],
                margin: [0, 0, 0, 25],
            },

            // Steps Table
            {
                table: {
                    headerRows: 1,
                    widths: ['5%', '15%', '15%', '25%', '15%', '10%', '15%'],
                    body: [
                        // Header
                        [
                            {
                                text: '#',
                                bold: true,
                                fillColor: '#1e293b',
                                color: 'white',
                                fontSize: 9,
                            },
                            {
                                text: 'Role',
                                bold: true,
                                fillColor: '#1e293b',
                                color: 'white',
                                fontSize: 9,
                            },
                            {
                                text: 'Step Name',
                                bold: true,
                                fillColor: '#1e293b',
                                color: 'white',
                                fontSize: 9,
                            },
                            {
                                text: 'Description',
                                bold: true,
                                fillColor: '#1e293b',
                                color: 'white',
                                fontSize: 9,
                            },
                            {
                                text: 'Value / Result',
                                bold: true,
                                fillColor: '#1e293b',
                                color: 'white',
                                fontSize: 9,
                            },
                            {
                                text: 'Units',
                                bold: true,
                                fillColor: '#1e293b',
                                color: 'white',
                                fontSize: 9,
                            },
                            {
                                text: 'Initials',
                                bold: true,
                                fillColor: '#1e293b',
                                color: 'white',
                                fontSize: 9,
                            },
                        ],
                        // Data rows
                        ...steps.map((step, idx) => {
                            const rowData = filled
                                ? executionData?.[step.id]
                                : null;
                            return [
                                {
                                    text: (idx + 1).toString(),
                                    fontSize: 8,
                                },
                                {
                                    text: step.roleName,
                                    fontSize: 8,
                                },
                                {
                                    text: step.name,
                                    fontSize: 8,
                                },
                                {
                                    text: step.description || '--',
                                    fontSize: 7,
                                },
                                {
                                    text: filled && rowData?.value
                                        ? rowData.value
                                        : '________________',
                                    fontSize: 8,
                                },
                                {
                                    text: filled && rowData?.units
                                        ? rowData.units
                                        : '____',
                                    fontSize: 8,
                                },
                                {
                                    text: filled && rowData?.initials
                                        ? rowData.initials
                                        : '____',
                                    fontSize: 8,
                                },
                            ];
                        }),
                    ],
                },
                margin: [0, 0, 0, 30],
            },

            // Role Signature Block
            {
                text: 'Role Sign-Off',
                fontSize: 11,
                bold: true,
                margin: [0, 0, 0, 15],
            },

            {
                table: {
                    headerRows: 0,
                    widths: ['33%', '34%', '33%'],
                    body: roles.map((role) => [
                        {
                            stack: [
                                { text: role.name, fontSize: 8, bold: true },
                                { text: '', margin: [0, 10, 0, 0] },
                                {
                                    text: '_______________________',
                                    fontSize: 8,
                                },
                                {
                                    text: 'Signature / Date',
                                    fontSize: 7,
                                    color: '#666',
                                },
                            ],
                            border: [false, false, false, false],
                            fontSize: 8,
                        },
                    ]),
                },
            },
        ],
    };

    const fileName = filled
        ? `BatchRecord_${experimentName}_COMPLETED.pdf`
        : `BatchRecord_${experimentName}_BLANK.pdf`;

    pdfMake.createPdf(docDefinition).download(fileName);
}

/**
 * Format parameter object into readable string for PDF display.
 */
function formatParams(params?: Record<string, any>): string {
    if (!params || Object.keys(params).length === 0) return '--';
    return Object.entries(params)
        .map(([key, val]) => `${key}: ${val}`)
        .join('; ');
}

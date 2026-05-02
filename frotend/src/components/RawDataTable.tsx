import React, { useState, memo } from "react";
import { Database, Loader2 } from "lucide-react";
import { api } from "../api/api";

interface RawDataTableProps {
  data: any[];
  hasData?: boolean;
  queryId?: string | number;
}

export const RawDataTable = memo(
  ({
    data: initialData,
    hasData,
    queryId,
  }: RawDataTableProps) => {
    const [data, setData] = useState(initialData);
    const [loading, setLoading] = useState(false);

    const handleToggle = async (e: React.SyntheticEvent) => {
      const details = e.target as HTMLDetailsElement;

      if (details.open && data.length === 0 && hasData && queryId) {
        setLoading(true);
        try {
          const result = await api.fetchQueryData(queryId);
          setData(result.raw_data || []);
        } catch (error) {
          console.error("Failed to load historical data", error);
        } finally {
          setLoading(false);
        }
      }
    };

    if (!initialData && !hasData) return null;

    const columns = data.length > 0 ? Object.keys(data[0]) : [];

    return (
      <div className="raw-data-table-wrapper">
        <details onToggle={handleToggle}>
          <summary className="raw-data-summary">
            <Database size={16} style={{ marginRight: "8px", opacity: 0.7 }} />
            View Data{" "}
            {data.length > 0
              ? `(${data.length} rows)`
              : hasData
                ? "(Click to load)"
                : ""}
          </summary>
          <div
            className="raw-data-scroll"
            style={{
              minHeight: loading ? "100px" : "auto",
              display: "flex",
              flexDirection: "column",
            }}
          >
            {loading ? (
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  padding: "2rem",
                  gap: "10px",
                  color: "var(--text-secondary)",
                }}
              >
                <Loader2 className="spinner" size={20} />
                Loading historical data...
              </div>
            ) : data.length > 0 ? (
              <table className="raw-data-table">
                <thead>
                  <tr>
                    <th style={{ width: "40px" }}>#</th>
                    {columns.map((col) => (
                      <th key={col}>{col.replace(/_/g, " ")}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {data.map((row, i) => (
                    <tr key={i}>
                      <td style={{ opacity: 0.5, fontSize: "0.75rem" }}>
                        {i + 1}
                      </td>
                      {columns.map((col) => (
                        <td key={col}>
                          {row[col] != null ? String(row[col]) : "—"}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <div style={{ padding: "1rem", textAlign: "center", opacity: 0.6 }}>
                No data available.
              </div>
            )}
          </div>
        </details>
      </div>
    );
  },
);

import React, { useState, memo, useMemo, useEffect } from "react";
import { Database, Loader2, ArrowUp, ArrowDown, ArrowUpDown, Search, X } from "lucide-react";
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
    const [rawDataTable, setRawDataTable] = useState<any[]>(initialData || []);
    const [loading, setLoading] = useState(false);
    const [sortConfig, setSortConfig] = useState<{ key: string | null; direction: 'asc' | 'desc' | null }>({ key: null, direction: null });
    const [filters, setFilters] = useState<{ [key: string]: string }>({});
    const [activeFilters, setActiveFilters] = useState<{ [key: string]: boolean }>({});

    // Sync with initialData if it changes
    useEffect(() => {
      if (initialData) setRawDataTable(initialData);
    }, [initialData]);

    const handleToggle = async (e: React.SyntheticEvent) => {
      const details = e.target as HTMLDetailsElement;

      if (details.open && rawDataTable.length === 0 && hasData && queryId) {
        setLoading(true);
        try {
          const result = await api.fetchQueryData(queryId);
          setRawDataTable(result.raw_data || []);
        } catch (error) {
          console.error("Failed to load historical data", error);
        } finally {
          setLoading(false);
        }
      }
    };

    const columns = useMemo(() => (rawDataTable.length > 0 ? Object.keys(rawDataTable[0]) : []), [rawDataTable]);

    const handleSort = (key: string) => {
      let direction: 'asc' | 'desc' | null = 'asc';
      if (sortConfig.key === key) {
        if (sortConfig.direction === 'asc') direction = 'desc';
        else if (sortConfig.direction === 'desc') direction = null;
      }
      setSortConfig({ key: direction ? key : null, direction });
    };

    const handleFilterChange = (key: string, value: string) => {
      setFilters(prev => ({ ...prev, [key]: value }));
    };

    const toggleFilter = (e: React.MouseEvent, key: string) => {
      e.stopPropagation();
      setActiveFilters(prev => ({ ...prev, [key]: !prev[key] }));
    };

    const filteredAndSortedData = useMemo(() => {
      let result = [...rawDataTable];

      // Filter
      Object.keys(filters).forEach(key => {
        const val = filters[key].toLowerCase();
        if (val) {
          result = result.filter(row => 
            String(row[key] ?? "").toLowerCase().includes(val)
          );
        }
      });

      // Sort
      if (sortConfig.key && sortConfig.direction) {
        const { key, direction } = sortConfig;
        result.sort((a, b) => {
          const aVal = a[key];
          const bVal = b[key];
          if (aVal == null) return 1;
          if (bVal == null) return -1;
          
          if (typeof aVal === 'number' && typeof bVal === 'number') {
            return direction === 'asc' ? aVal - bVal : bVal - aVal;
          }
          
          const aStr = String(aVal).toLowerCase();
          const bStr = String(bVal).toLowerCase();
          if (aStr < bStr) return direction === 'asc' ? -1 : 1;
          if (aStr > bStr) return direction === 'asc' ? 1 : -1;
          return 0;
        });
      }

      return result;
    }, [rawDataTable, filters, sortConfig]);

    if (!initialData && !hasData) return null;

    return (
      <div className="raw-data-table-wrapper">
        <details onToggle={handleToggle}>
          <summary className="raw-data-summary">
            <Database size={16} style={{ marginRight: "8px", opacity: 0.7 }} />
            View Data{" "}
            {rawDataTable.length > 0
              ? `(${rawDataTable.length} rows)`
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
            ) : rawDataTable.length > 0 ? (
              <table className="raw-data-table">
                <thead>
                  <tr>
                    <th style={{ width: "40px" }}>#</th>
                    {columns.map((col) => (
                      <th key={col} className="sortable-header" onClick={() => handleSort(col)}>
                        <div className="header-content">
                          <span className="col-name">{col.replace(/_/g, " ")}</span>
                          <div className="header-actions">
                            <button 
                              className={`filter-btn ${filters[col] ? 'active' : ''}`} 
                              onClick={(e) => toggleFilter(e, col)}
                              title="Filter column"
                            >
                              <Search size={12} />
                            </button>
                            <div className="sort-icons">
                              {sortConfig.key === col ? (
                                sortConfig.direction === 'asc' ? <ArrowUp size={12} className="active" /> : <ArrowDown size={12} className="active" />
                              ) : (
                                <ArrowUpDown size={12} className="idle" />
                              )}
                            </div>
                          </div>
                        </div>
                        {activeFilters[col] && (
                          <div className="filter-row" onClick={e => e.stopPropagation()}>
                            <div className="filter-input-container">
                              <input
                                autoFocus
                                type="text"
                                placeholder={`Search...`}
                                value={filters[col] || ""}
                                onChange={(e) => handleFilterChange(col, e.target.value)}
                                onKeyDown={(e) => {
                                  if (e.key === "Escape") {
                                    setActiveFilters(prev => ({ ...prev, [col]: false }));
                                  }
                                }}
                                className="filter-input"
                              />
                              {filters[col] && (
                                <button className="clear-filter" onClick={() => handleFilterChange(col, "")}>
                                  <X size={10} />
                                </button>
                              )}
                            </div>
                          </div>
                        )}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {filteredAndSortedData.map((row, i) => (
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

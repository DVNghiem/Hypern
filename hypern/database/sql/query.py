from enum import Enum
from typing import Any, Dict, List, Tuple, Union
from hypern.database.sql.field import ForeignKey


class JoinType(Enum):
    INNER = "INNER JOIN"
    LEFT = "LEFT JOIN"
    RIGHT = "RIGHT JOIN"
    FULL = "FULL JOIN"
    CROSS = "CROSS JOIN"


class Operator(Enum):
    EQ = "="
    GT = ">"
    LT = "<"
    GTE = ">="
    LTE = "<="
    NEQ = "!="
    IN = "IN"
    NOT_IN = "NOT IN"
    LIKE = "LIKE"
    ILIKE = "ILIKE"
    BETWEEN = "BETWEEN"
    IS_NULL = "IS NULL"
    IS_NOT_NULL = "IS NOT NULL"
    REGEXP = "~"
    IREGEXP = "~*"


class Expression:
    """Class for representing SQL expressions with parameters"""

    def __init__(self, sql: str, params: list):
        self.sql = sql
        self.params = params

    def over(self, partition_by=None, order_by=None, frame=None, window_name=None):  # NOSONAR
        """
        Add OVER clause for window functions with support for:
        - Named windows
        - Custom frame definitions
        - Flexible partitioning and ordering
        """
        if window_name:
            self.sql = f"{self.sql} OVER {window_name}"
            return self

        parts = ["OVER("]
        clauses = []

        if partition_by:
            if isinstance(partition_by, str):
                partition_by = [partition_by]
            # Handle both raw SQL and Django-style field references
            formatted_fields = []
            for field in partition_by:
                if "__" in field:  # Django-style field reference
                    field = field.replace("__", ".")
                formatted_fields.append(field)
            clauses.append(f"PARTITION BY {', '.join(formatted_fields)}")

        if order_by:
            if isinstance(order_by, str):
                order_by = [order_by]
            # Handle both raw SQL and Django-style ordering
            formatted_order = []
            for field in order_by:
                if isinstance(field, str):
                    if field.startswith("-"):
                        field = f"{field[1:]} DESC"
                    elif field.startswith("+"):
                        field = f"{field[1:]} ASC"
                    if "__" in field:  # Django-style field reference
                        field = field.replace("__", ".")
                formatted_order.append(field)
            clauses.append(f"ORDER BY {', '.join(formatted_order)}")

        if frame:
            if isinstance(frame, str):
                clauses.append(frame)
            elif isinstance(frame, (list, tuple)):
                frame_type = "ROWS"  # Default frame type
                if len(frame) == 3 and frame[0].upper() in ("ROWS", "RANGE", "GROUPS"):
                    frame_type = frame[0].upper()
                    frame = frame[1:]
                frame_clause = f"{frame_type} BETWEEN {frame[0]} AND {frame[1]}"
                clauses.append(frame_clause)

        parts.append(" ".join(clauses))
        parts.append(")")

        self.sql = f"{self.sql} {' '.join(parts)}"
        return self


class F:
    """Class for creating SQL expressions and column references"""

    def __init__(self, field: str):
        self.field = field.replace("__", ".")

    def __add__(self, other):
        if isinstance(other, F):
            return Expression(f"{self.field} + {other.field}", [])
        return Expression(f"{self.field} + ?", [other])

    def __sub__(self, other):
        if isinstance(other, F):
            return Expression(f"{self.field} - {other.field}", [])
        return Expression(f"{self.field} - ?", [other])

    def __mul__(self, other):
        if isinstance(other, F):
            return Expression(f"{self.field} * {other.field}", [])
        return Expression(f"{self.field} * ?", [other])

    def __truediv__(self, other):
        if isinstance(other, F):
            return Expression(f"{self.field} / {other.field}", [])
        return Expression(f"{self.field} / ?", [other])

    # Window function methods
    def sum(self):
        """SUM window function"""
        return Expression(f"SUM({self.field})", [])

    def avg(self):
        """AVG window function"""
        return Expression(f"AVG({self.field})", [])

    def count(self):
        """COUNT window function"""
        return Expression(f"COUNT({self.field})", [])

    def max(self):
        """MAX window function"""
        return Expression(f"MAX({self.field})", [])

    def min(self):
        """MIN window function"""
        return Expression(f"MIN({self.field})", [])

    def lag(self, offset=1, default=None):
        """LAG window function"""
        if default is None:
            return Expression(f"LAG({self.field}, {offset})", [])
        return Expression(f"LAG({self.field}, {offset}, ?)", [default])

    def lead(self, offset=1, default=None):
        """LEAD window function"""
        if default is None:
            return Expression(f"LEAD({self.field}, {offset})", [])
        return Expression(f"LEAD({self.field}, {offset}, ?)", [default])

    def row_number(self):
        """ROW_NUMBER window function"""
        return Expression("ROW_NUMBER()", [])

    def rank(self):
        """RANK window function"""
        return Expression("RANK()", [])

    def dense_rank(self):
        """DENSE_RANK window function"""
        return Expression("DENSE_RANK()", [])


class Window:
    """Class for defining named windows"""

    def __init__(self, name: str, partition_by=None, order_by=None, frame=None):
        self.name = name
        self.partition_by = partition_by
        self.order_by = order_by
        self.frame = frame

    def to_sql(self):  # NOSONAR
        """Convert window definition to SQL"""
        parts = [f"{self.name} AS ("]
        clauses = []

        if self.partition_by:
            if isinstance(self.partition_by, str):
                self.partition_by = [self.partition_by]
            formatted_fields = [f.replace("__", ".") for f in self.partition_by]
            clauses.append(f"PARTITION BY {', '.join(formatted_fields)}")

        if self.order_by:
            if isinstance(self.order_by, str):
                self.order_by = [self.order_by]
            formatted_order = []
            for field in self.order_by:
                if field.startswith("-"):
                    field = f"{field[1:].replace('__', '.')} DESC"
                elif field.startswith("+"):
                    field = f"{field[1:].replace('__', '.')} ASC"
                else:
                    field = field.replace("__", ".")
                formatted_order.append(field)
            clauses.append(f"ORDER BY {', '.join(formatted_order)}")

        if self.frame:
            if isinstance(self.frame, str):
                clauses.append(self.frame)
            elif isinstance(self.frame, (list, tuple)):
                frame_type = "ROWS"
                if len(self.frame) == 3 and self.frame[0].upper() in ("ROWS", "RANGE", "GROUPS"):
                    frame_type = self.frame[0].upper()
                    self.frame = self.frame[1:]
                frame_clause = f"{frame_type} BETWEEN {self.frame[0]} AND {self.frame[1]}"
                clauses.append(frame_clause)

        parts.append(" ".join(clauses))
        parts.append(")")
        return " ".join(parts)


class Q:
    """Class for complex WHERE conditions with AND/OR operations"""

    def __init__(self, *args, **kwargs):
        self.children = list(args)
        self.connector = "AND"
        self.negated = False

        if kwargs:
            # Convert kwargs to Q objects and add them
            for key, value in kwargs.items():
                condition = {key: value}
                self.children.append(condition)

    def __and__(self, other):
        if getattr(other, "connector", "AND") == "AND" and not other.negated:
            # If other is also an AND condition and not negated,
            # we can merge their children
            clone = self._clone()
            clone.children.extend(other.children)
            return clone
        else:
            q = Q()
            q.connector = "AND"
            q.children = [self, other]
            return q

    def __or__(self, other):
        if getattr(other, "connector", "OR") == "OR" and not other.negated:
            # If other is also an OR condition and not negated,
            # we can merge their children
            clone = self._clone()
            clone.connector = "OR"
            clone.children.extend(other.children)
            return clone
        else:
            q = Q()
            q.connector = "OR"
            q.children = [self, other]
            return q

    def __invert__(self):
        clone = self._clone()
        clone.negated = not self.negated
        return clone

    def _clone(self):
        """Create a copy of the current Q object"""
        clone = Q()
        clone.connector = self.connector
        clone.negated = self.negated
        clone.children = self.children[:]
        return clone

    def add(self, child, connector):
        """Add a child node, updating connector if necessary"""
        if connector != self.connector:
            # If connectors don't match, we need to nest the existing children
            self.children = [Q(*self.children, connector=self.connector)]
            self.connector = connector

        if isinstance(child, Q):
            if child.connector == connector and not child.negated:
                # If child has same connector and is not negated,
                # we can merge its children directly
                self.children.extend(child.children)
            else:
                self.children.append(child)
        else:
            self.children.append(child)

    def _combine(self, other, connector):
        """
        Combine this Q object with another one using the given connector.
        This is an internal method used by __and__ and __or__.
        """
        if not other:
            return self._clone()

        if not self:
            return other._clone() if isinstance(other, Q) else Q(other)

        q = Q()
        q.connector = connector
        q.children = [self, other]
        return q

    def __bool__(self):
        """Return True if this Q object has any children"""
        return bool(self.children)

    def __str__(self):
        """
        Return a string representation of the Q object,
        useful for debugging
        """
        if self.negated:
            return f"NOT ({self._str_inner()})"
        return self._str_inner()

    def _str_inner(self):
        """Helper method for __str__"""
        if not self.children:
            return ""

        children_str = []
        for child in self.children:
            if isinstance(child, Q):
                child_str = str(child)
            elif isinstance(child, dict):
                child_str = " AND ".join(f"{k}={v}" for k, v in child.items())  # NOSONAR
            else:
                child_str = str(child)
            children_str.append(f"({child_str})")

        return f" {self.connector} ".join(children_str)


class QuerySet:
    def __init__(self, model):
        self.model = model
        self.query_parts = {
            "select": ["*"],
            "where": [],
            "order_by": [],
            "limit": None,
            "offset": None,
            "joins": [],
            "group_by": [],
            "having": [],
            "with": [],
            "window": [],
        }
        self.params = []
        self._distinct = False
        self._for_update = False
        self._for_share = False
        self._nowait = False
        self._skip_locked = False
        self._param_counter = 1
        self._selected_related = set()

    def __get_next_param(self):
        param_name = f"${self._param_counter}"
        self._param_counter += 1
        return param_name

    def clone(self) -> "QuerySet":
        new_qs = QuerySet(self.model)
        new_qs.query_parts = {k: v[:] if isinstance(v, list) else v for k, v in self.query_parts.items()}
        new_qs.params = self.params[:]
        new_qs._distinct = self._distinct
        new_qs._for_update = self._for_update
        new_qs._for_share = self._for_share
        new_qs._nowait = self._nowait
        new_qs._skip_locked = self._skip_locked
        new_qs._param_counter = self._param_counter
        new_qs._selected_related = self._selected_related.copy()
        return new_qs

    def select(self, *fields, distinct: bool = False) -> "QuerySet":
        qs = self.clone()
        qs.query_parts["select"] = list(map(lambda x: f"{qs.model.Meta.table_name}.{x}" if x != "*" else x, fields))
        qs._distinct = distinct
        return qs

    def _process_q_object(self, q_obj: Q, params: List = None) -> Tuple[str, List]:
        if params is None:
            params = []

        if not q_obj.children:
            return "", params

        sql_parts = []
        local_params = []

        for child in q_obj.children:
            if isinstance(child, Q):
                inner_sql, inner_params = self._process_q_object(child)
                sql_parts.append(f"({inner_sql})")
                local_params.extend(inner_params)
            elif isinstance(child, dict):
                for key, value in child.items():
                    field_sql, field_params = self._process_where_item(key, value)
                    sql_parts.append(field_sql)
                    local_params.extend(field_params)
            elif isinstance(child, tuple):
                field_sql, field_params = self._process_where_item(child[0], child[1])
                sql_parts.append(field_sql)
                local_params.extend(field_params)

        joined = f" {q_obj.connector} ".join(sql_parts)
        if q_obj.negated:
            joined = f"NOT ({joined})"

        params.extend(local_params)
        return joined, params

    def _process_where_item(self, key: str, value: Any) -> Tuple[str, List]:
        parts = key.split("__")
        field = parts[0]
        op = "=" if len(parts) == 1 else parts[1]

        if isinstance(value, F):
            return self._process_f_value(field, op, value)

        if isinstance(value, Expression):
            return self._process_expression_value(field, op, value)

        return self._process_standard_value(field, op, value)

    def _process_f_value(self, field: str, op: str, value: F) -> Tuple[str, List]:
        return f"{self.model.Meta.table_name}.{field} {op} {value.field}", []

    def _process_expression_value(self, field: str, op: str, value: Expression) -> Tuple[str, List]:
        return f"{self.model.Meta.table_name}.{field} {op} {value.sql}", value.params

    def _process_standard_value(self, field: str, op: str, value: Any) -> Tuple[str, List]:
        op_map = {
            "gt": Operator.GT.value,
            "lt": Operator.LT.value,
            "gte": Operator.GTE.value,
            "lte": Operator.LTE.value,
            "contains": Operator.LIKE.value,
            "icontains": Operator.ILIKE.value,
            "startswith": Operator.LIKE.value,
            "endswith": Operator.LIKE.value,
            "in": Operator.IN.value,
            "not_in": Operator.NOT_IN.value,
            "isnull": Operator.IS_NULL.value,
            "between": Operator.BETWEEN.value,
            "regex": Operator.REGEXP.value,
            "iregex": Operator.IREGEXP.value,
        }

        if op in op_map:
            return self._process_op_map_value(field, op, value, op_map)
        else:
            param_name = self.__get_next_param()
            return f"{self.model.Meta.table_name}.{field} = {param_name}", [value]

    def _process_op_map_value(self, field: str, op: str, value: Any, op_map: dict) -> Tuple[str, List]:
        param_name = self.__get_next_param()
        combine_field_name = f"{self.model.Meta.table_name}.{field}"
        if op in ("contains", "icontains"):
            return f"{combine_field_name} {op_map[op]} {param_name}", [f"%{value}%"]
        elif op == "startswith":
            return f"{combine_field_name} {op_map[op]} {param_name}", [f"{value}%"]
        elif op == "endswith":
            return f"{combine_field_name} {op_map[op]} {param_name}", [f"%{value}"]
        elif op == "isnull":
            return f"{combine_field_name} {Operator.IS_NULL.value if value else Operator.IS_NOT_NULL.value}", []
        elif op == "between":
            return f"{combine_field_name} {op_map[op]} {param_name} AND {param_name}", [value[0], value[1]]
        elif op in ("in", "not_in"):
            placeholders = ",".join(["{param_name}" for _ in value])
            return f"{combine_field_name} {op_map[op]} ({placeholders})", list(value)
        else:
            return f"{combine_field_name} {op_map[op]} {param_name}", [value]

    def where(self, *args, **kwargs) -> "QuerySet":
        qs = self.clone()

        # Process Q objects
        for arg in args:
            if isinstance(arg, Q):
                sql, params = qs._process_q_object(arg, [])
                if sql:
                    qs.query_parts["where"].append(sql)
                    qs.params.extend(params)
            elif isinstance(arg, Expression):
                qs.query_parts["where"].append(arg.sql)
                qs.params.extend(arg.params)
            else:
                qs.query_parts["where"].append(str(arg))

        # Process keyword arguments
        if kwargs:
            q = Q(**kwargs)
            sql, params = qs._process_q_object(q, [])
            if sql:
                qs.query_parts["where"].append(sql)
                qs.params.extend(params)
        return qs

    def annotate(self, **annotations) -> "QuerySet":
        qs = self.clone()
        select_parts = []

        for alias, expression in annotations.items():
            if isinstance(expression, F):
                select_parts.append(f"{expression.field} AS {alias}")
            elif isinstance(expression, Expression):
                select_parts.append(f"({expression.sql.replace('?', qs.__get_next_param())}) AS {alias}")
                qs.params.extend(expression.params)
            else:
                select_parts.append(f"{expression} AS {alias}")

        qs.query_parts["select"].extend(select_parts)
        return qs

    def values(self, *fields) -> "QuerySet":
        return self.select(*fields)

    def values_list(self, *fields, flat: bool = False) -> "QuerySet":
        if flat and len(fields) > 1:
            raise ValueError("'flat' is not valid when values_list is called with more than one field.")
        return self.select(*fields)

    def order_by(self, *fields) -> "QuerySet":
        qs = self.clone()
        order_parts = []

        for field in fields:
            if isinstance(field, F):
                order_parts.append(field.field)
            elif isinstance(field, Expression):
                order_parts.append(field.sql)
                qs.params.extend(field.params)
            elif field.startswith("-"):
                order_parts.append(f"{field[1:]} DESC")
            else:
                order_parts.append(f"{qs.model.Meta.table_name}.{field} ASC")

        qs.query_parts["order_by"] = order_parts
        return qs

    def select_related(self, *fields) -> "QuerySet":
        """
        Include related objects in the query results.

        Args:
            *fields: Names of foreign key fields to include
        """
        qs = self.clone()
        for field in fields:
            if field in qs.model._fields and isinstance(qs.model._fields[field], ForeignKey):
                qs._selected_related.add(field)
        return qs

    def join(self, table: Any, on: Union[str, Expression], join_type: Union[str, JoinType] = JoinType.INNER) -> "QuerySet":
        qs = self.clone()
        joined_table = table.Meta.table_name if hasattr(table, "Meta") else table

        if isinstance(join_type, JoinType):
            join_type = join_type.value

        if isinstance(on, Expression):
            qs.query_parts["joins"].append(f"{join_type} {joined_table} ON {on.sql}")
            qs.params.extend(on.params)
        else:
            qs.query_parts["joins"].append(f"{join_type} {joined_table} ON {on}")

        return qs

    def group_by(self, *fields) -> "QuerySet":
        qs = self.clone()
        group_parts = []

        for field in fields:
            if isinstance(field, F):
                group_parts.append(field.field)
            elif isinstance(field, Expression):
                group_parts.append(field.sql)
                qs.params.extend(field.params)
            else:
                group_parts.append(f"{qs.model.Meta.table_name}.{field}")

        qs.query_parts["group_by"] = group_parts
        return qs

    def having(self, *conditions) -> "QuerySet":
        qs = self.clone()
        having_parts = []

        for condition in conditions:
            if isinstance(condition, Expression):
                having_parts.append(condition.sql)
                qs.params.extend(condition.params)
            else:
                having_parts.append(str(condition))

        qs.query_parts["having"] = having_parts
        return qs

    def window(self, alias: str, partition_by: List = None, order_by: List = None) -> "QuerySet":
        qs = self.clone()
        parts = [f"{alias} AS ("]

        if partition_by:
            parts.append(qs._process_partition_by(partition_by, qs))

        if order_by:
            parts.append(qs._process_order_by(order_by, qs))

        parts.append(")")
        qs.query_parts["window"].append(" ".join(parts))
        return qs

    def _process_partition_by(self, partition_by: List, qs: "QuerySet") -> str:
        partition_parts = []
        for field in partition_by:
            if isinstance(field, F):
                partition_parts.append(field.field)
            elif isinstance(field, Expression):
                partition_parts.append(field.sql)
                qs.params.extend(field.params)
            else:
                partition_parts.append(f"{self.model.Meta.table_name}.{field}")
        return f"PARTITION BY {', '.join(partition_parts)}"

    def _process_order_by(self, order_by: List, qs: "QuerySet") -> str:
        order_parts = []
        for field in order_by:
            if isinstance(field, F):
                order_parts.append(field.field)
            elif isinstance(field, Expression):
                order_parts.append(field.sql)
                qs.params.extend(field.params)
            elif field.startswith("-"):
                order_parts.append(f"{qs.model.Meta.table_name}.{field[1:]} DESC")
            else:
                order_parts.append(f"{qs.model.Meta.table_name}.{field} ASC")
        return f"ORDER BY {', '.join(order_parts)}"

    def limit(self, limit: int) -> "QuerySet":
        qs = self.clone()
        qs.query_parts["limit"] = limit
        return qs

    def offset(self, offset: int) -> "QuerySet":
        qs = self.clone()
        qs.query_parts["offset"] = offset
        return qs

    def for_update(self, nowait: bool = False, skip_locked: bool = False) -> "QuerySet":
        qs = self.clone()
        qs._for_update = True
        qs._nowait = nowait
        qs._skip_locked = skip_locked
        return qs

    def for_share(self, nowait: bool = False, skip_locked: bool = False) -> "QuerySet":
        qs = self.clone()
        qs._for_share = True
        qs._nowait = nowait
        qs._skip_locked = skip_locked
        return qs

    def with_recursive(self, name: str, initial_query: str, recursive_query: str) -> "QuerySet":
        qs = self.clone()
        cte = f"WITH RECURSIVE {name} AS ({initial_query} UNION ALL {recursive_query})"
        qs.query_parts["with"].append(cte)
        return qs

    def union(self, other_qs: "QuerySet", all: bool = False) -> "QuerySet":
        sql1, params1 = self.to_sql()
        sql2, params2 = other_qs.to_sql()
        union_type = "UNION ALL" if all else "UNION"
        combined_sql = f"({sql1}) {union_type} ({sql2})"
        combined_params = params1 + params2

        new_qs = self.clone()
        new_qs.query_parts["raw_sql"] = combined_sql
        new_qs.params = combined_params
        return new_qs

    def intersect(self, other_qs: "QuerySet", all: bool = False) -> "QuerySet":
        sql1, params1 = self.to_sql()
        sql2, params2 = other_qs.to_sql()
        intersect_type = "INTERSECT ALL" if all else "INTERSECT"
        combined_sql = f"({sql1}) {intersect_type} ({sql2})"
        combined_params = params1 + params2

        new_qs = self.clone()
        new_qs.query_parts["raw_sql"] = combined_sql
        new_qs.params = combined_params
        return new_qs

    def except_(self, other_qs: "QuerySet", all: bool = False) -> "QuerySet":
        sql1, params1 = self.to_sql()
        sql2, params2 = other_qs.to_sql()
        except_type = "EXCEPT ALL" if all else "EXCEPT"
        combined_sql = f"({sql1}) {except_type} ({sql2})"
        combined_params = params1 + params2

        new_qs = self.clone()
        new_qs.query_parts["raw_sql"] = combined_sql
        new_qs.params = combined_params
        return new_qs

    def subquery(self, alias: str) -> Expression:
        """Convert this queryset into a subquery expression"""
        sql, params = self.to_sql()
        return Expression(f"({sql}) AS {alias}", params)

    def to_sql(self) -> Tuple[str, List]:
        """Convert the QuerySet into an SQL query string and parameters"""
        if "raw_sql" in self.query_parts:
            return self.query_parts["raw_sql"], self.params

        parts = []
        self._build_sql_parts(parts)
        return " ".join(parts), self.params

    def _build_sql_parts(self, parts):
        self._add_with_clause(parts)
        self._add_select_clause(parts)
        self._add_from_clause(parts)
        self._add_joins_clause(parts)
        self._add_where_clause(parts)
        self._add_group_by_clause(parts)
        self._add_having_clause(parts)
        self._add_window_clause(parts)
        self._add_order_by_clause(parts)
        self._add_limit_clause(parts)
        self._add_offset_clause(parts)
        self._add_locking_clauses(parts)

    def _add_with_clause(self, parts):
        if self.query_parts["with"]:
            parts.append(" ".join(self.query_parts["with"]))

    def _add_select_clause(self, parts):
        select_clause = "SELECT"
        if self._distinct:
            select_clause += " DISTINCT"

        # Add selected fields
        select_related_fields = []
        for field in self._selected_related:
            related_table = self.model._fields[field].to_model
            select_related_fields.append(f"{related_table}.*")

        select_clause += " " + ", ".join(self.query_parts["select"] + select_related_fields)
        parts.append(select_clause)

    def _add_from_clause(self, parts):
        parts.append(f"FROM {self.model.Meta.table_name}")

    def _add_joins_clause(self, parts):
        if self.query_parts["joins"]:
            parts.extend(self.query_parts["joins"])

    def _add_where_clause(self, parts):
        if self.query_parts["where"]:
            parts.append("WHERE " + " AND ".join(f"({condition})" for condition in self.query_parts["where"]))

    def _add_group_by_clause(self, parts):
        if self.query_parts["group_by"]:
            parts.append("GROUP BY " + ", ".join(self.query_parts["group_by"]))

    def _add_having_clause(self, parts):
        if self.query_parts["having"]:
            parts.append("HAVING " + " AND ".join(self.query_parts["having"]))

    def _add_window_clause(self, parts):
        if self.query_parts["window"]:
            parts.append("WINDOW " + ", ".join(self.query_parts["window"]))

    def _add_order_by_clause(self, parts):
        if self.query_parts["order_by"]:
            parts.append("ORDER BY " + ", ".join(self.query_parts["order_by"]))

    def _add_limit_clause(self, parts):
        if self.query_parts["limit"] is not None:
            parts.append(f"LIMIT {self.query_parts['limit']}")

    def _add_offset_clause(self, parts):
        if self.query_parts["offset"] is not None:
            parts.append(f"OFFSET {self.query_parts['offset']}")

    def _add_locking_clauses(self, parts):
        if self._for_update:
            parts.append("FOR UPDATE")
            if self._nowait:
                parts.append("NOWAIT")
            elif self._skip_locked:
                parts.append("SKIP LOCKED")
        elif self._for_share:
            parts.append("FOR SHARE")
            if self._nowait:
                parts.append("NOWAIT")
            elif self._skip_locked:
                parts.append("SKIP LOCKED")

    def execute(self) -> List[Tuple]:
        """Execute the query and return results"""
        sql, params = self.to_sql()
        result = self.model.get_session().fetch_all(sql, params)
        return result

    def count(self) -> int:
        """Return the count of rows that would be returned by this query"""
        qs = self.clone()
        qs.query_parts["select"] = ["COUNT(*)"]
        qs.query_parts["order_by"] = []  # Clear order_by as it's unnecessary for count
        sql, params = qs.to_sql()

        # Execute count query
        result = self.model.get_session().fetch_all(sql, params)
        return result

    def exists(self) -> bool:
        """Return True if the query would return any results"""
        qs = self.clone()
        qs.query_parts["select"] = ["1"]
        qs.query_parts["order_by"] = []
        qs = qs.limit(1)
        sql, params = qs.to_sql()

        result = self.model.get_session().fetch_all(sql, params)
        return result

    def update(self, **kwargs) -> int:
        """Update records that match the query conditions"""
        updates = []
        params = []

        for field, value in kwargs.items():
            param_name = self.__get_next_param()
            if isinstance(value, F):
                updates.append(f"{field} = {value.field}")
            elif isinstance(value, Expression):
                updates.append(f"{field} = {value.sql}")
                params.extend(value.params)
            else:
                updates.append(f"{field} = {param_name}")
                params.append(value)

        where_sql = " AND ".join(f"({condition})" for condition in self.query_parts["where"])

        sql = f"UPDATE {self.model.Meta.table_name} SET {', '.join(updates)}"
        if where_sql:
            sql += f" WHERE {where_sql}"
        params = self.params + params
        result = self.model.get_session().bulk_change(sql, [params], 1)
        return result

    def delete(self) -> int:
        """Delete records that match the query conditions"""
        where_sql = " AND ".join(f"({condition})" for condition in self.query_parts["where"])

        sql = f"DELETE FROM {self.model.Meta.table_name}"
        if where_sql:
            sql += f" WHERE {where_sql}"

        return self.model.get_session().bulk_change(sql, [self.params], 1)

    def bulk_create(self, objs: List[Any], batch_size: int = None) -> int | None:
        """Insert multiple records in an efficient way"""
        if not objs:
            return

        # Get fields from the first object
        fields = [name for name, f in self.model._fields.items() if not f.auto_increment]
        placeholders = ",".join([self.__get_next_param() for _ in fields])

        sql = f"INSERT INTO {self.model.Meta.table_name} ({','.join(fields)}) VALUES ({placeholders})"

        values = []
        for obj in objs:
            values.append([obj._data[i] for i in fields])

        return self.model.get_session().bulk_change(sql, values, batch_size or len(values))

    def explain(self, analyze: bool = False, verbose: bool = False, costs: bool = False, buffers: bool = False, timing: bool = False) -> Dict:
        """Get the query execution plan"""
        options = []
        if analyze:
            options.append("ANALYZE")
        if verbose:
            options.append("VERBOSE")
        if costs:
            options.append("COSTS")
        if buffers:
            options.append("BUFFERS")
        if timing:
            options.append("TIMING")

        sql, params = self.to_sql()
        explain_sql = f"EXPLAIN ({' '.join(options)}) {sql}"

        result = self.model.get_session().fetch_all(explain_sql, params)
        return result

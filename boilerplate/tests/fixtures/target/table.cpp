namespace store {

class Table {
public:
    ~Table() { delete[] rows_; }
    int size() const { return count_; }
    int *row(int index);

private:
    int *rows_ = nullptr;
    int count_ = 0;
};

int *Table::row(int index)
{
    return rows_ + index;
}

}  // namespace store

template <class T, class U> struct Pair { int first() { return 1; } };
template <class T> struct Pair<T, int> { int second() { return 2; } };
struct Point { friend bool operator==(const Point &, const Point &) { return true; } };

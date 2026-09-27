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
